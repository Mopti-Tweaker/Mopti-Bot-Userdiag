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
import time

# Configuration des logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Charger les variables d'environnement
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Vérification des variables d'environnement
if not all([DISCORD_TOKEN, MISTRAL_API_KEY, CHANNEL_ID]):
    logger.error("Variables d'environnement manquantes !")
    raise ValueError("Variables d'environnement manquantes !")

if not CHANNEL_ID.isdigit():
    logger.error("CHANNEL_ID doit être un nombre entier valide.")
    raise ValueError("CHANNEL_ID doit être un nombre entier valide.")

CHANNEL_ID = int(CHANNEL_ID)

# Base de données des prestations et leurs prix
PRESTATIONS = {
    "DDR4": {
        "Overclock CPU": 20,
        "Overclock CPU + RAM": 65,
        "Overclock RAM + GPU": 55,
        "Overclock CPU + RAM + GPU": 85
    },
    "DDR5": {
        "Overclock CPU": 40,
        "Overclock CPU + RAM": 155,
        "Overclock RAM + GPU": 135,
        "Overclock CPU + RAM + GPU": 195
    }
}

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

# Fonction pour extraire les composants
def extract_components(text):
    components = {
        "CPU": None,
        "RAM": None,
        "GPU": None
    }

    # Déterminer le type de RAM
    if "DDR4" in text.upper():
        components["RAM"] = "DDR4"
    elif "DDR5" in text.upper():
        components["RAM"] = "DDR5"

    # Extraire le CPU
    cpu_keywords = ["CPU:", "PROCESSEUR:", "AMD", "INTEL", "RYZEN", "CORE I"]
    for keyword in cpu_keywords:
        if keyword in text.upper():
            cpu_start = text.upper().find(keyword)
            if cpu_start != -1:
                cpu_line = text[cpu_start:].split("\n")[0]
                components["CPU"] = cpu_line.strip()
                break

    # Extraire le GPU
    gpu_keywords = ["GPU:", "CARTE GRAPHIQUE:", "NVIDIA", "AMD RADEON", "RTX", "GTX"]
    for keyword in gpu_keywords:
        if keyword in text.upper():
            gpu_start = text.upper().find(keyword)
            if gpu_start != -1:
                gpu_line = text[gpu_start:].split("\n")[0]
                components["GPU"] = gpu_line.strip()
                break

    return components

# Fonction pour envoyer le texte à Mistral
def send_to_mistral(text):
    components = extract_components(text)
    ram_type = components["RAM"]

    if not ram_type:
        return "Impossible de déterminer le type de RAM."

    try:
        url = "https://api.mistral.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "mistral-small",
            "messages": [
                {
                    "role": "user",
                    "content": f"""
                    Voici les composants identifiés :
                    - RAM: {ram_type}
                    - CPU: {components["CPU"]}
                    - GPU: {components["GPU"]}

                    **Analyse ces composants et réponds uniquement avec les informations suivantes :**

                    1. Détermine quels composants peuvent être overclockés parmi CPU, RAM et GPU.
                    2. Utilise les prix suivants pour les prestations :
                        - {ram_type} :
                            - Overclock CPU : {20 if ram_type == "DDR4" else 40}€
                            - Overclock CPU + RAM : {65 if ram_type == "DDR4" else 155}€
                            - Overclock RAM + GPU : {55 if ram_type == "DDR4" else 135}€
                            - Overclock CPU + RAM + GPU : {85 if ram_type == "DDR4" else 195}€

                    **Format de réponse strict :**
                    ```
                    Tu peux faire :
                    [Liste des composants overclockables parmi CPU, RAM, GPU]

                    Ce qui correspond à la prestation : [Nom de la prestation] à **[prix]€**
                    ```

                    **Exemple de réponse :**
                    ```
                    Tu peux faire :
                    - Un Overclock CPU
                    - Un Overclock de la RAM

                    Ce qui correspond à la prestation : Overclock CPU + RAM à **65€**
                    ```

                    **Règles strictes :**
                    - Ne mentionne que les composants qui peuvent être overclockés.
                    - Choisis la prestation et le prix en fonction du type de RAM et des composants overclockables.
                    - Pour les prestations DDR5, ajoute "(Paiement en plusieurs fois possible)" à la fin de la ligne de prix.
                    - Respecte strictement le format de réponse.
                    """
                }
            ]
        }
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()

        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            retry_after = int(e.response.headers.get('Retry-After', 10))
            logger.error(f"Trop de requêtes. Attente de {retry_after} secondes...")
            time.sleep(retry_after)
            return send_to_mistral(text)  # Réessayer après le délai
        else:
            logger.error(f"Erreur HTTP lors de l'appel à l'API Mistral : {e}")
            return f"Erreur HTTP : {e}"
    except Exception as e:
        logger.error(f"Erreur lors de l'appel à l'API Mistral : {e}")
        return f"Erreur : {e}"

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
                        await message.channel.send(f"```{result}```")
                    else:
                        await message.channel.send("Impossible d'extraire le texte du fichier.")
                except Exception as e:
                    logger.error(f"Erreur lors du traitement du fichier : {e}")
                    await message.channel.send(f"Erreur : {e}")

# Route pour UptimeRobot
@app.route('/ping')
def ping():
    return "Bot is alive!", 200

# Lancer le bot Discord dans un thread séparé
def run_bot():
    logger.info("Démarrage du bot Discord...")
    bot.run(DISCORD_TOKEN)

# Lancer le serveur Flask
def run_flask():
    logger.info("Démarrage du serveur Flask...")
    app.run(host='0.0.0.0', port=10000)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_flask()
