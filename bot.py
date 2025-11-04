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
import json

# Charger les variables d'environnement
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

# Initialiser Flask pour UptimeRobot
app = Flask(__name__)

# Initialiser le bot Discord
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Fonction pour extraire le texte d'un PDF
def extract_text_from_pdf(pdf_bytes):
    text = ""
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"
    return text

# Fonction pour extraire le texte d'un HTML
def extract_text_from_html(html_bytes):
    soup = BeautifulSoup(html_bytes, "html.parser")
    return soup.get_text()

# Fonction pour envoyer le texte à Mistral
def send_to_mistral(text):
    url = "https://api.mistral.ai/v1/models/mistral-tiny/chat"  # Remplace par l'URL correcte de l'API Mistral si différente
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "mistral-tiny",  # Remplace par le modèle que tu utilises
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
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        return f"Erreur lors de l'appel à l'API Mistral : {response.text}"

# Événement : Bot prêt
@bot.event
async def on_ready():
    print(f"Bot connecté en tant que {bot.user}")

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
                    result = send_to_mistral(text)
                    await message.channel.send(result)
                except Exception as e:
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
    threading.Thread(target=run_bot).start()
    run_flask()
