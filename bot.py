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
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Vérification des variables d'environnement
if not all([DISCORD_TOKEN, CHANNEL_ID]):
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
    gpu_keywords = ["NVIDIA", "AMD RADEON", "GTX", "RTX", "Intel UHD", "Intel Iris"]
    for keyword in gpu_keywords:
        if keyword in text:
            gpu_start = text.find(keyword)
            if gpu_start != -1:
                gpu_line = text[gpu_start:].split("\n")[0]
                info["GPU"] = gpu_line.strip()
                break

    return info

# Fonction pour déterminer les possibilités d'overclocking
def determine_overclocking(info):
    if info["is_laptop"]:
        return [], "Pas de prestation pour PC portable", 0

    cpu = info["CPU"]
    carte_mere = info["carte_mere"]
    ram_type = info["RAM"]
    gpu = info["GPU"]

    overclockable = []

    # Règles pour l'overclocking du CPU
    if "AMD Ryzen" in cpu:
        if carte_mere and ("B" in carte_mere or "X" in carte_mere):
            overclockable.append("CPU")
    elif "Intel" in cpu:
        if "K" in cpu or "KF" in cpu or "KS" in cpu:
            if carte_mere and ("Z" in carte_mere):
                overclockable.append("CPU")

    # Règles pour l'overclocking de la RAM
    if "AMD Ryzen" in cpu:
        if carte_mere and ("B" in carte_mere or "X" in carte_mere):
            overclockable.append("RAM")
    elif "Intel" in cpu:
        if carte_mere and ("Z" in carte_mere or carte_mere in ["B560", "B660", "B760"]):
            overclockable.append("RAM")

    # Règles pour l'overclocking du GPU
    if gpu:
        if "NVIDIA" in gpu or "AMD RADEON" in gpu or "RTX" in gpu or "GTX" in gpu:
            if not ("Intel UHD" in gpu or "Intel Iris" in gpu):
                overclockable.append("GPU")

    # Déterminer la prestation et le prix
    prestation = ""
    prix = 0

    if len(overclockable) == 0:
        prestation = "Aucune prestation d'overclocking disponible"
        prix = 0
    elif len(overclockable) == 1 and "GPU" in overclockable:
        prestation = "Overclock GPU"
        prix = PRESTATIONS[ram_type][prestation]
    elif len(overclockable) == 2 and "CPU" in overclockable and "RAM" in overclockable:
        prestation = "Overclock CPU + RAM"
        prix = PRESTATIONS[ram_type][prestation]
    elif len(overclockable) == 2 and "CPU" in overclockable and "GPU" in overclockable:
        prestation = "Overclock CPU + GPU"
        prix = PRESTATIONS[ram_type][prestation]
    elif len(overclockable) == 2 and "RAM" in overclockable and "GPU" in overclockable:
        prestation = "Overclock RAM + GPU"
        prix = PRESTATIONS[ram_type][prestation]
    elif len(overclockable) == 3:
        prestation = "Overclock CPU + RAM + GPU"
        prix = PRESTATIONS[ram_type][prestation]

    return overclockable, prestation, prix

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
                        overclockable, prestation, prix = determine_overclocking(info)

                        # Générer la réponse
                        if prestation == "Aucune prestation d'overclocking disponible":
                            response = prestation
                        else:
                            response = f"Tu peux faire :\n"
                            for component in overclockable:
                                response += f"- Un Overclock {component}\n"

                            if prestation:
                                response += f"\nCe qui correspond à la prestation : {prestation} à **{prix}€**"
                                if info["RAM"] == "DDR5":
                                    response += " (Paiement en plusieurs fois possible)"

                        await message.channel.send(f"```{response}```")
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
