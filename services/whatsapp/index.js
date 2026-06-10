const fs = require("fs");
const path = require("path");
const http = require("http");
const pino = require("pino");

// Baileys is ESM — use dynamic import so this works on Node.js 20 (Render) as well as Node 24 (local)
let makeWASocket, useMultiFileAuthState, DisconnectReason;

const STATE_FILE = path.join(__dirname, "qr-state.json");
const AUTH_DIR = path.join(__dirname, "auth");
const API_BASE = process.env.API_URL || "http://localhost:8000";
const BOT_PORT = parseInt(process.env.BOT_PORT || "3001", 10);
const WEBHOOK_SECRET = process.env.BAILEYS_WEBHOOK_SECRET || "";

function writeState(state) {
    try {
        fs.writeFileSync(STATE_FILE, JSON.stringify({ ...state, updated_at: new Date().toISOString() }, null, 2));
    } catch (err) {
        console.error("writeState error:", err.message);
    }
}

let sock = null;
let lastActive = Date.now();
let autoReconnect = true;
let isPairingMode = false;

function clearAuthDir() {
    try {
        if (fs.existsSync(AUTH_DIR)) {
            const files = fs.readdirSync(AUTH_DIR);
            for (const f of files) {
                const fp = path.join(AUTH_DIR, f);
                try { fs.unlinkSync(fp); } catch {}
            }
            console.log(`Cleared ${files.length} stale auth file(s)`);
        }
    } catch (err) {
        console.error("clearAuthDir error:", err.message);
    }
}

async function forwardToApi(body, socketForReply = null, retries = 2) {
    const url = `${API_BASE}/api/baileys/webhook`;
    for (let attempt = 0; attempt <= retries; attempt++) {
        try {
            const headers = { "Content-Type": "application/json" };
            if (WEBHOOK_SECRET) headers["X-Baileys-Secret"] = WEBHOOK_SECRET;
            const resp = await fetch(url, {
                method: "POST", headers,
                body: JSON.stringify(body),
                signal: AbortSignal.timeout(15000),
            });
            if (!resp.ok) {
                const text = await resp.text().catch(() => "");
                console.error(`API returned ${resp.status}: ${text.slice(0, 200)}`);
                if (attempt < retries) {
                    await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
                    continue;
                }
                return;
            }
            const data = await resp.json();
            if (data.reply && data.to) {
                const ok = await sendMessage(data.to, data.reply, socketForReply);
                if (!ok && attempt < retries) {
                    await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
                    continue;
                }
            }
            return;
        } catch (err) {
            console.error(`forwardToApi attempt ${attempt + 1}/${retries + 1}:`, err.message);
            if (attempt < retries) {
                await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
            }
        }
    }
}

async function sendMessage(jid, text, socketForReply = null) {
    const s = socketForReply || sock;
    if (!s) return false;
    try {
        await s.sendMessage(jid, { text });
        return true;
    } catch (err) {
        // If the original socket failed and there's a newer global socket, try that
        if (s !== sock && sock) {
            try {
                await sock.sendMessage(jid, { text });
                return true;
            } catch (err2) {
                console.error("sendMessage: primary failed, fallback also failed:", err2.message);
                return false;
            }
        }
        console.error("sendMessage error:", err.message);
        return false;
    }
}

function setupEventHandlers(socket, onConnected) {
    socket.ev.on("connection.update", async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            writeState({ connected: false, qr, message: "QR code ready — use pairing code instead from dashboard." });
        }

        if (connection === "open") {
            console.log("WhatsApp connected");
            isPairingMode = false;
            autoReconnect = true;
            lastActive = Date.now();
            writeState({ connected: true, qr: null, message: "WhatsApp is connected." });
            try { await socket.sendPresenceUpdate("available"); } catch {}
            if (onConnected) onConnected();
        }

        if (connection === "close") {
            const reason = lastDisconnect?.error?.output?.statusCode;
            console.log(`Connection closed (reason: ${reason})`);

            // Only null global sock if this socket is still the active one
            const nullSock = () => { if (sock === socket) sock = null; };

            if (reason === DisconnectReason.loggedOut) {
                writeState({ connected: false, qr: null, message: "Logged out. Re-pair from dashboard." });
                nullSock();
                return;
            }

            if (reason === 408) {
                if (isPairingMode) {
                    console.log("408 during pairing — reconnecting without clearing auth");
                    nullSock();
                    startBot().catch(err => console.error("Restart after 408 (pairing) failed:", err.message));
                } else {
                    console.log("408 — clearing stale auth and restarting for fresh QR");
                    clearAuthDir();
                    writeState({ connected: false, qr: null, message: "Ready for pairing. Refresh or enter your phone number to pair." });
                    nullSock();
                    startBot().catch(err => console.error("Restart after 408 failed:", err.message));
                }
                return;
            }

            // Log stream errors to state so the user can see them
            const errMsg = lastDisconnect?.error?.message || lastDisconnect?.error?.reason || "";
            if (errMsg && !["", "Connection Terminated"].includes(errMsg)) {
                writeState({ connected: false, qr: null, message: `Disconnected: ${errMsg}` });
            }

            if (autoReconnect) {
                console.log("Auto-reconnecting in 5s...");
                setTimeout(() => startBot(), 5000);
            } else {
                nullSock();
                writeState({ connected: false, qr: null, message: "Disconnected. Reconnect from dashboard." });
            }
        }
    });

    socket.ev.on("messages.upsert", async (msg) => {
        lastActive = Date.now();
        const m = msg.messages[0];
        if (!m.message || m.key.fromMe) return;

        const msgType = Object.keys(m.message).find(k => k.endsWith("Message")) || "unknown";
        const text = m.message.conversation
            || m.message.extendedTextMessage?.text
            || m.message.imageMessage?.caption
            || m.message.videoMessage?.caption
            || m.message.documentMessage?.caption
            || "";

        if (!text.trim()) {
            if (msgType !== "conversation" && msgType !== "extendedTextMessage") {
                console.log(`Skipping ${msgType} from ${m.key.remoteJid} (no caption)`);
            }
            return;
        }

        const sender = m.key.remoteJid;
        const pushName = m.pushName || "";
        let profilePicUrl = null;
        try { profilePicUrl = await socket.profilePictureUrl(sender, "image"); } catch {}

        console.log(`Incoming from ${pushName || sender}:`, text.slice(0, 80));

        await forwardToApi({
            from: sender, body: text, message_id: m.key.id,
            push_name: pushName, profile_pic_url: profilePicUrl,
            to: socket.user?.id || "",
        }, socket);
    });
}

async function startBot(noReconnect = false) {
    if (sock) {
        try { sock.end(undefined); } catch {}
        sock = null;
    }
    if (noReconnect) autoReconnect = false;

    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const logger = pino({ level: process.env.LOG_LEVEL || "warn" });

    sock = makeWASocket({
        auth: state,
        printQRInTerminal: false,
        markOnlineOnConnect: true,
        connectTimeoutMs: 60000,
        keepAliveIntervalMs: 25000,
        retryRequestDelayMs: 2000,
        maxRetryCount: 3,
        defaultQueryTimeoutMs: 60000,
        syncFullHistory: false,
        fireInitQueries: false,
        browser: ["Chrome (Mac OS)", "Safari", "14.4.1"],
        generateHighQualityLinkPreview: false,
        logger,
    });

    writeState({ connected: false, qr: null, message: "Connecting..." });

    setupEventHandlers(sock, () => {
        // connected callback
    });

    sock.ev.on("creds.update", saveCreds);
}

async function requestPairingCode(phone) {
    if (!phone) throw new Error("Phone number is required");

    // Already connected — don't disrupt an active session
    if (sock?.user) {
        return "already_connected";
    }

    clearAuthDir();

    if (sock) {
        try { sock.end(undefined); } catch {}
        sock = null;
    }
    autoReconnect = false;

    writeState({ connected: false, qr: null, message: "Requesting pairing code..." });

    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const logger = pino({ level: process.env.LOG_LEVEL || "warn" });

    const pairingSock = makeWASocket({
        auth: state,
        printQRInTerminal: false,
        markOnlineOnConnect: true,
        connectTimeoutMs: 60000,
        keepAliveIntervalMs: 25000,
        retryRequestDelayMs: 2000,
        maxRetryCount: 2,
        defaultQueryTimeoutMs: 60000,
        syncFullHistory: false,
        fireInitQueries: false,
        browser: ["Chrome (Mac OS)", "Safari", "14.4.1"],
        generateHighQualityLinkPreview: false,
        logger,
    });

    pairingSock.ev.on("creds.update", saveCreds);

    const code = await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
            cleanup();
            reject(new Error("Timeout waiting for WebSocket connection"));
        }, 30000);

        let done = false;

        function cleanup() {
            if (done) return;
            done = true;
            clearTimeout(timeout);
            pairingSock.ev.off("connection.update", handler);
        }

        const handler = async (update) => {
            if (done) return;

            if (update.connection === "open") {
                cleanup();
                resolve("already_connected");
                return;
            }

            if (update.qr) {
                try {
                    const pairingCode = await pairingSock.requestPairingCode(phone);
                    cleanup();
                    resolve(pairingCode);
                } catch (err) {
                    cleanup();
                    reject(err);
                }
                return;
            }

            if (update.connection === "close") {
                const reason = update.lastDisconnect?.error?.output?.statusCode;
                cleanup();
                const msg = reason === 408
                    ? "Connection timed out (408). Try again."
                    : `Connection closed (reason: ${reason || "unknown"}). Try again.`;
                reject(new Error(msg));
            }
        };

        pairingSock.ev.on("connection.update", handler);
    });

    const formatted = String(code).match(/.{1,4}/g)?.join("-") || String(code);
    writeState({
        connected: false,
        qr: null,
        pairing_code: formatted,
        message: `Pairing code: ${formatted}`,
    });
    console.log(`Pairing code generated for ${phone}: ${formatted}`);

    autoReconnect = true;

    // Remove temp handlers, set up full handlers, and make this the active socket
    pairingSock.ev.removeAllListeners("connection.update");
    pairingSock.ev.removeAllListeners("creds.update");
    pairingSock.ev.removeAllListeners("messages.upsert");

    sock = pairingSock;
    isPairingMode = true;
    setupEventHandlers(sock);
    sock.ev.on("creds.update", saveCreds);

    return formatted;
}

// ===== HTTP Server =====
const server = http.createServer(async (req, res) => {
    const sendJson = (code, data) => {
        res.writeHead(code, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
    };
    const body = await new Promise((resolve) => {
        let data = "";
        req.on("data", (chunk) => data += chunk);
        req.on("end", () => resolve(data));
    });

    try {
        const url = new URL(req.url, `http://localhost:${BOT_PORT}`);
        const pathname = url.pathname;

        if (req.method === "GET" && pathname === "/health") {
            return sendJson(200, { ok: true, connected: sock?.user ? true : false });
        }

        if (req.method === "GET" && pathname === "/qr") {
            let state = {};
            try { state = JSON.parse(fs.readFileSync(STATE_FILE, "utf-8")); } catch {}
            return sendJson(200, { connected: !!state.connected, qr: state.qr || null, message: state.message || "" });
        }

        if (req.method === "GET" && pathname === "/profile-pic") {
            const jid = url.searchParams.get("jid");
            if (!jid) return sendJson(400, { error: "Missing jid param" });
            let picUrl = null;
            try { picUrl = await sock?.profilePictureUrl(jid, "image"); } catch {}
            return sendJson(200, { jid, profile_pic_url: picUrl });
        }

        if (req.method === "POST" && pathname === "/request-pairing-code") {
            const data = JSON.parse(body || "{}");
            const phone = String(data.phone || "").replace(/[^0-9]/g, "");
            if (!phone) return sendJson(400, { error: "Phone number is required" });

            try {
                const code = await requestPairingCode(phone);
                return sendJson(200, { pairing_code: code, phone });
            } catch (err) {
                console.error("Pairing code error:", err.message);
                writeState({ connected: false, qr: null, message: `Pairing failed: ${err.message}` });
                return sendJson(500, { error: err.message });
            }
        }

        if (req.method === "POST" && pathname === "/restart") {
            console.log("Restarting bot with fresh auth...");
            clearAuthDir();
            if (sock) { try { sock.end(undefined); } catch {} sock = null; }
            autoReconnect = true;
            startBot().catch(err => {
                console.error("Restart bot failed:", err.message);
                writeState({ connected: false, qr: null, message: `Restart failed: ${err.message}` });
            });
            return sendJson(200, { ok: true, message: "Bot restarted. QR will regenerate." });
        }

        if (req.method === "POST" && pathname === "/send") {
            const data = JSON.parse(body || "{}");
            const jid = data.to;
            const text = data.body;
            if (!jid || !text) return sendJson(400, { error: "Missing 'to' or 'body'" });
            const ok = await sendMessage(jid, text);
            return sendJson(ok ? 200 : 500, { sent: ok });
        }

        return sendJson(404, { error: "Not found" });
    } catch (err) {
        return sendJson(500, { error: err.message });
    }
});

// Write state immediately on process start (synchronous — runs before any async init)
writeState({ connected: false, qr: null, message: "Bot process started, loading modules..." });

// Start the bot after dynamic import of Baileys (ESM module — not requireable on Node 20)
(async () => {
    try {
        const mod = await import("@whiskeysockets/baileys");
        makeWASocket = mod.default;
        useMultiFileAuthState = mod.useMultiFileAuthState;
        DisconnectReason = mod.DisconnectReason;
        writeState({ connected: false, qr: null, message: "Baileys loaded, initializing..." });
    } catch (err) {
        console.error("Failed to load Baileys:", err.message);
        writeState({ connected: false, qr: null, message: `Baileys load failed: ${err.message}` });
        return;
    }

    // Keep-alive ping every 30s
    setInterval(() => {
        if (sock?.user) {
            sock.sendPresenceUpdate("available").catch(() => {});
        }
    }, 30000);

    server.listen(BOT_PORT, "127.0.0.1", () => {
        console.log(`WhatsApp bot listening on 127.0.0.1:${BOT_PORT}`);
        writeState({ connected: false, qr: null, message: "Bot listening, initializing WhatsApp connection..." });
        startBot().catch(err => {
            console.error("Initial startBot failed:", err.message);
            writeState({ connected: false, qr: null, message: `Bot failed: ${err.message}. Refresh to retry.` });
        });
    });
})();
