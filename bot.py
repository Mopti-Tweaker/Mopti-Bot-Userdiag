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
        "Overclock GPU": 30,
        "Overclock CPU + RAM": 65,
        "Overclock CPU + GPU": 75,
        "Overclock RAM + GPU": 55,
        "Overclock CPU + RAM + GPU": 85
    },
    "DDR5": {
        "Overclock GPU": 30,
        "Overclock CPU + RAM": 155,
        "Overclock CPU + GPU": 175,
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

# Fonction pour extraire les informations du HTML
def extract_info_from_html(html_bytes):
    soup = BeautifulSoup(html_bytes, "html.parser")
    text = soup.get_text()

    info = {
        "RAM": None,
        "carte_mere": None,
        "CPU": None,
        "GPU": None,
        "is_laptop": False
    }

    # Vérifier si c'est un PC portable
    if "Laptop" in text or "Notebook" in text or "Portable" in text:
        info["is_laptop"] = True

    # Extraire le type de RAM
    if "DDR4" in text:
        info["RAM"] = "DDR4"
    elif "DDR5" in text:
        info["RAM"] = "DDR5"

    # Extraire la carte mère
    carte_mere_keywords = ["A520M", "B450M", "B550", "X570", "Z590", "B560", "B660", "B760"]
    for keyword in carte_mere_keywords:
        if keyword in text:
            info["carte_mere"] = keyword
            break

    # Extraire le CPU
    if "AMD" in text or "Intel" in text:
        cpu_start = text.find("AMD") if "AMD" in text else text.find("Intel")
        if cpu_start != -1:
            cpu_line = text[cpu_start:].split("\n")[0]
            info["CPU"] = cpu_line.strip()

    # Extraire le GPU
    gpu_keywords = ["NVIDIA", "AMD", "RADEON", "GTX", "RTX"]
    for keyword in gpu_keywords:
        if keyword in text:
            gpu_start = text.find(keyword)
            if gpu_start != -1:
                gpu_line = text[gpu_start:].split("\n")[0]
                info["GPU"] = gpu_line.strip()
                break

    return info

# Fonction pour envoyer les informations à Mistral
def send_to_mistral(info):
    try:
        url = "https://api.mistral.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json"
        }

        # Vérifier si c'est un PC portable
        if info["is_laptop"]:
            return "Pas de prestation d'overclocking disponible pour les PC portables."

        data = {
            "model": "mistral-small",
            "messages": [
                {
                    "role": "user",
                    "content": f"""
                    Voici les informations d'un diagnostic PC :
                    - RAM: {info["RAM"]}
                    - Carte mère: {info["carte_mere"]}
                    - CPU: {info["CPU"]}
                    - GPU: {info["GPU"]}

                    **Règles strictes pour l'overclocking :**

                    1. Overclock CPU AMD :
                       - Possible uniquement si c'est un AMD Ryzen ET si la carte mère est de modèle B ou X.

                    2. Overclock CPU Intel :
                       - Possible uniquement si c'est un processeur modèle K, KF ou KS ET si la carte mère est de modèle Z.

                    3. Overclock de la RAM sur CPU Intel :
                       - Possible uniquement si la carte mère est de modèle Z, B560, B660 ou B760.

                    4. Overclock de la RAM sur CPU AMD :
                       - Possible uniquement si c'est un AMD Ryzen ET si la carte mère est de modèle B ou X.

                    5. Overclock du GPU :
                       - Possible uniquement si c'est une carte graphique NVIDIA ou AMD.
                       - Pas possible si c'est une carte graphique Intel (Intel UHD, Intel Iris).

                    **Instructions :**
                    - Détermine quels composants peuvent être overclockés en fonction des règles ci-dessus.
                    - Utilise les prix suivants pour les prestations :
                        - DDR4 :
                            - Overclock GPU : 30€
                            - Overclock CPU + RAM : 65€
                            - Overclock CPU + GPU : 75€
                            - Overclock RAM + GPU : 55€
                            - Overclock CPU + RAM + GPU : 85€
                        - DDR5 :
                            - Overclock GPU : 135€
                            - Overclock CPU + RAM : 155€
                            - Overclock CPU + GPU : 175€
                            - Overclock RAM + GPU : 135€
                            - Overclock CPU + RAM + GPU : 195€

                    **Format de réponse strict :**
                    ```
                    Tu peux faire :
                    [Liste des composants overclockables parmi CPU, RAM, GPU]

                    Ce qui correspond à la prestation : [Nom de la prestation] à **€[prix]**
                    ```
                    - Ne mentionne que les composants qui peuvent être overclockés.
                    - Respecte strictement le format de réponse.
                    - Pour les prestations DDR5, ajoute "(Paiement en plusieurs fois possible)" à la fin de la ligne de prix.
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
            return send_to_mistral(info)  # Réessayer après le délai
        else:
            logger.error(f"Erreur HTTP lors de l'appel à l'API Mistral : {e}")
            return f"Erreur HTTP : {e}"
    except Exception as e:
        logger.error(f"Erreur lors de l'appel à l'API Mistral : {e}")
        return f"Erreur : {e}"

# Événement : Message reçu
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.channel.id != CHANNEL_ID:
        return
    if len(message.attachments) > 0:
        for attachment in message.attachments:
            if attachment.filename.endswith(".html"):
                await message.channel.send(f"Analyse de {attachment.filename} en cours...")
                file_content = await attachment.read()
                try:
                    info = extract_info_from_html(file_content)
                    if info["RAM"] and info["carte_mere"] and info["CPU"]:
                        result = send_to_mistral(info)
                        await message.channel.send(f"```{result}```")
                    else:
                        await message.channel.send("Impossible d'extraire les informations nécessaires du fichier.")
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
