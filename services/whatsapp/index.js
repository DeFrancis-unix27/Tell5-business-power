const fs = require("fs");
const path = require("path");
const { default: makeWASocket, useMultiFileAuthState } = require("@whiskeysockets/baileys");
const qrcode = require("qrcode-terminal");

const statePath = path.join(__dirname, "qr-state.json");

function writeState(state) {
    try {
        fs.writeFileSync(statePath, JSON.stringify({ ...state, updated_at: new Date().toISOString() }, null, 2));
    } catch (err) {
        console.error("Failed to write WhatsApp QR state:", err);
    }
}

async function startBot() {
    const { state, saveCreds } = await useMultiFileAuthState("auth");

    const sock = makeWASocket({
        auth: state,
        printQRInTerminal: false
    });

    writeState({ connected: false, qr: null, message: "Waiting for WhatsApp QR code..." });

    sock.ev.on("connection.update", (update) => {
        const { connection, qr } = update;

        if (qr) {
            qrcode.generate(qr, { small: true });
            writeState({ connected: false, qr, message: "Scan this code with WhatsApp to connect." });
        }

        if (connection === "open") {
            console.log("✅ WhatsApp connected!");
            writeState({ connected: true, qr: null, message: "WhatsApp is connected." });
        }

        if (connection === "close") {
            console.log("❌ Connection closed. Restarting...");
            writeState({ connected: false, qr: null, message: "Connection closed. Restart the service to reconnect." });
            startBot();
        }
    });

    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("messages.upsert", async (msg) => {
        const message = msg.messages[0];

        if (!message.message || message.key.fromMe) return;

        const text =
            message.message.conversation ||
            message.message.extendedTextMessage?.text;

        console.log("📩 Received:", text);

        // temporary reply
        await sock.sendMessage(message.key.remoteJid, {
            text: "Hello 👋 I received your message"
        });
    });
}

startBot();