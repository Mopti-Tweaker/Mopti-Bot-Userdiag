import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import requests
from io import BytesIO
import pdfplumber
from bs4 import BeautifulSoup
from flask import Flask
import threading
import logging

# Configuration des logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Charger les variables d'environnement
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Vérification des variables d'environnement
if not DISCORD_TOKEN or not MISTRAL_API_KEY or not CHANNEL_ID:
    raise ValueError("Les variables d'environnement DISCORD_TOKEN, MISTRAL_API_KEY et CHANNEL_ID sont requises.")

if not CHANNEL_ID.isdigit():
    raise ValueError("CHANNEL_ID doit être un nombre entier valide.")

CHANNEL_ID = int(CHANNEL_ID)

# Initialiser Flask pour UptimeRobot
app = Flask(__name__)

# Initialiser le bot Discord
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Fonction pour extraire le texte d'un PDF
def extract_text_from_pdf(pdf_bytes):
    try:
        text = ""
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text += page.extract_text() + "\n"
        return text
    except Exception as e:
        logger.error(f"Erreur lors de l'extraction du PDF : {e}")
        return None

# Fonction pour extraire le texte d'un HTML
def extract_text_from_html(html_bytes):
    try:
        soup = BeautifulSoup(html_bytes, "html.parser")
        return soup.get_text()
    except Exception as e:
        logger.error(f"Erreur lors de l'extraction du HTML : {e}")
        return None

# Fonction pour envoyer le texte à Mistral
def send_to_mistral(text):
    try:
        url = "https://api.mistral.ai/v1/models/mistral-tiny/chat"
        headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "mistral-tiny",
            "messages": [
                {
                    "role": "user",
                    "content": f"""
                    Analyse les résultats de diagnostic suivants pour déterminer les possibilités d'overclocking (CPU, RAM, GPU) :
                    {text}
                    Retourne une réponse structurée sous la forme :
                    'Sur ton PC, il est possible de faire un Overclock CPU, un Overclock RAM, ce qui correspond à la prestation OC CPU RAM à **€[prix]**.'
                    """
                }
            ]
        }
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Erreur lors de l'appel à l'API Mistral : {e}")
        return f"Erreur lors de l'analyse : {e}"

# Événement : Bot prêt
@bot.event
async def on_ready():
    logger.info(f"Bot connecté en tant que {bot.user}")

# Événement : Message reçu
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.channel.id != CHANNEL_ID:
        return
    if len(message.attachments) > 0:
        for attachment in message.attachments:
            if attachment.filename.endswith((".pdf", ".html")):
                await message.channel.send(f"Analyse de {attachment.filename} en cours...")
                file_content = await attachment.read()
                try:
                    if attachment.filename.endswith(".pdf"):
                        text = extract_text_from_pdf(file_content)
                    else:
                        text = extract_text_from_html(file_content)
                    if text:
                        result = send_to_mistral(text)
                        await message.channel.send(result)
                    else:
                        await message.channel.send("Impossible d'extraire le texte du fichier.")
                except Exception as e:
                    logger.error(f"Erreur lors du traitement du fichier : {e}")
                    await message.channel.send(f"Erreur lors de l'analyse : {e}")

# Route pour UptimeRobot
@app.route('/ping')
def ping():
    return "Bot is alive!", 200

# Lancer le bot Discord dans un thread séparé
def run_bot():
    bot.run(DISCORD_TOKEN)

# Lancer le serveur Flask
def run_flask():
    app.run(host='0.0.0.0', port=10000)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_flask()
