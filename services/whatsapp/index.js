const { default: makeWASocket, useMultiFileAuthState } = require("@whiskeysockets/baileys");
const qrcode = require("qrcode-terminal");

async function startBot() {
    const { state, saveCreds } = await useMultiFileAuthState("auth");

    const sock = makeWASocket({
        auth: state,
        printQRInTerminal: false
    });

    sock.ev.on("connection.update", (update) => {
        const { connection, qr } = update;

        if (qr) {
            qrcode.generate(qr, { small: true });
        }

        if (connection === "open") {
            console.log("✅ WhatsApp connected!");
        }

        if (connection === "close") {
            console.log("❌ Connection closed. Restarting...");
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