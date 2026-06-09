const fs = require("fs");
const path = require("path");
const http = require("http");
const pino = require("pino");
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason } = require("@whiskeysockets/baileys");

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

async function forwardToApi(body, retries = 2) {
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
                await sendMessage(data.to, data.reply);
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

async function sendMessage(jid, text) {
    if (!sock) return false;
    try {
        await sock.sendMessage(jid, { text });
        return true;
    } catch (err) {
        console.error("sendMessage error:", err.message);
        return false;
    }
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

    sock.ev.on("connection.update", async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            writeState({ connected: false, qr, message: "QR code ready — use pairing code instead from dashboard." });
        }

        if (connection === "open") {
            console.log("WhatsApp connected");
            autoReconnect = true;
            lastActive = Date.now();
            writeState({ connected: true, qr: null, message: "WhatsApp is connected." });
            try { await sock.sendPresenceUpdate("available"); } catch {}
        }

        if (connection === "close") {
            const reason = lastDisconnect?.error?.output?.statusCode;
            console.log(`Connection closed (reason: ${reason})`);

            if (reason === DisconnectReason.loggedOut) {
                writeState({ connected: false, qr: null, message: "Logged out. Re-pair from dashboard." });
                sock = null;
                return;
            }

            // 408 = QR refs exhausted / registration timeout
            // Don't auto-reconnect — wait for pairing code from dashboard
            if (reason === 408) {
                writeState({ connected: false, qr: null, message: "Ready for pairing. Go to Connections page and enter your phone number." });
                sock = null;
                return;
            }

            // For other disconnects, auto-reconnect if allowed
            if (autoReconnect) {
                console.log("Auto-reconnecting in 5s...");
                setTimeout(() => startBot(), 5000);
            } else {
                sock = null;
                writeState({ connected: false, qr: null, message: "Disconnected. Reconnect from dashboard." });
            }
        }
    });

    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("messages.upsert", async (msg) => {
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
        try { profilePicUrl = await sock.profilePictureUrl(sender, "image"); } catch {}

        console.log(`Incoming from ${pushName || sender}:`, text.slice(0, 80));

        await forwardToApi({
            from: sender, body: text, message_id: m.key.id,
            push_name: pushName, profile_pic_url: profilePicUrl,
            to: sock.user?.id || "",
        });
    });
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

            // Start fresh socket for pairing — this one won't auto-reconnect on failure
            writeState({ connected: false, qr: null, message: "Requesting pairing code..." });
            startBot(true);

            // Wait for socket to be ready, then request pairing code
            for (let i = 0; i < 30; i++) {
                await new Promise(r => setTimeout(r, 1000));
                if (sock?.user) {
                    // Already connected somehow — shouldn't happen for fresh auth
                    return sendJson(200, { pairing_code: "already_connected", phone });
                }
                if (sock) {
                    try {
                        let code = await sock.requestPairingCode(phone);
                        code = code.match(/.{1,4}/g)?.join("-") || code;
                        writeState({ connected: false, qr: null, pairing_code: code, message: `Pairing code: ${code}` });
                        console.log(`Pairing code generated for ${phone}: ${code}`);
                        // Enable reconnect for the paired socket
                        autoReconnect = true;
                        return sendJson(200, { pairing_code: code, phone });
                    } catch (err) {
                        if (i < 5) {
                            // Early failures might be "not ready yet" — keep waiting
                            continue;
                        }
                        return sendJson(500, { error: err.message });
                    }
                }
            }
            return sendJson(500, { error: "Bot failed to initialize for pairing" });
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

// Keep-alive ping every 30s
setInterval(() => {
    if (sock?.user) {
        sock.sendPresenceUpdate("available").catch(() => {});
    }
}, 30000);

server.listen(BOT_PORT, "127.0.0.1", () => {
    console.log(`WhatsApp bot listening on 127.0.0.1:${BOT_PORT}`);
    startBot();
});