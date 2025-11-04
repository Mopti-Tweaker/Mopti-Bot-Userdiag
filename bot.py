import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import requests
from io import BytesIO
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

# Initialiser Flask pour UptimeRobot
app = Flask(__name__)

# Initialiser le bot Discord
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Fonction pour envoyer le fichier HTML à Mistral
def send_html_to_mistral(html_content):
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
                    Voici le contenu complet d'un fichier de diagnostic PC au format HTML :

                    ```html
                    {html_content}
                    ```

                    **Instructions pour l'analyse :**

                    1. Analyse ce fichier HTML pour extraire les informations suivantes :
                       - Type et fréquence de la RAM (vérifie chaque slot de RAM).
                       - Modèle de la carte mère.
                       - Modèle du CPU (AMD ou Intel, et si c'est un modèle K, KF, KS pour Intel).
                       - Modèle du GPU (NVIDIA, AMD, Intel).
                       - Si c'est un PC portable.

                    2. Applique les règles suivantes pour déterminer les possibilités d'overclocking :

                       **Overclock CPU :**
                       - AMD Ryzen : Possible uniquement si la carte mère est de modèle B ou X.
                       - Intel : Possible uniquement si le CPU est un modèle K, KF ou KS et si la carte mère est de modèle Z.

                       **Overclock RAM :**
                       - AMD Ryzen : Possible uniquement si la carte mère est de modèle B ou X.
                       - Intel : Possible uniquement si la carte mère est de modèle Z, B560, B660 ou B760.
                       - Vérifie aussi que les slots RAM ne sont pas vides.

                       **Overclock GPU :**
                       - Possible uniquement si le GPU est une carte NVIDIA ou AMD.
                       - Pas possible si le GPU est une carte Intel (Intel UHD, Intel Iris).

                       **Pas d'overclocking pour les PC portables.**

                    3. Utilise les prix suivants pour les prestations :
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

                    4. Retourne une réponse sous la forme suivante :

                    ```
                    Tu peux faire :
                    [Liste des composants overclockables parmi CPU, RAM, GPU]

                    Ce qui correspond à la prestation : [Nom de la prestation] à **€[prix]**
                    ```

                    - Ne mentionne que les composants qui peuvent être overclockés.
                    - Respecte strictement le format de réponse.
                    - Pour les prestations DDR5, ajoute "(Paiement en plusieurs fois possible)" à la fin de la ligne de prix.
                    - Si c'est un PC portable, réponds simplement : "Pas de prestation d'overclocking disponible pour les PC portables."
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
            return send_html_to_mistral(html_content)  # Réessayer après le délai
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
                    html_content = file_content.decode('utf-8')
                    result = send_html_to_mistral(html_content)
                    await message.channel.send(f"```{result}```")
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
