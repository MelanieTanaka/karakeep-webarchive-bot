import discord
import asyncio
import aiohttp
import os
import re

# --- Configuration: Read all from environment variables ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
KARAKEEP_API_KEY = os.getenv("KARAKEEP_API_KEY")
KARAKEEP_API_URL = os.getenv("KARAKEEP_API_URL")
DEFAULT_ARCHIVE_CHANNEL_ID = os.getenv("DEFAULT_ARCHIVE_CHANNEL_ID")
ARCHIVE_ALL_LINKS_IN_CHANNEL = os.getenv("ARCHIVE_ALL_LINKS_IN_CHANNEL", "false").lower() == "true"

# Wayback Machine Timeout (in seconds)
WAYBACK_MACHINE_TIMEOUT_SECONDS = int(os.getenv("WAYBACK_MACHINE_TIMEOUT_SECONDS", 180)) # Default 3 minutes

# Regex to find URLs in message content
URL_REGEX = r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"

# Create a Discord Bot instance
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

# --- Global aiohttp session for reuse ---
http_session: aiohttp.ClientSession = None
target_channel: discord.TextChannel = None

# --- Helper function to get/ensure HTTP session ---
async def get_http_session():
    global http_session
    if http_session is None or http_session.closed:
        print("HTTP session is not active or closed. Recreating...", flush=True)
        http_session = aiohttp.ClientSession()
    return http_session

@bot.event
async def on_ready():
    global target_channel # http_session is now managed by get_http_session

    # Initial session creation when bot first comes online
    await get_http_session() 
    print(f'We have logged in as {bot.user}', flush=True)

    if DEFAULT_ARCHIVE_CHANNEL_ID:
        try:
            channel_id = int(DEFAULT_ARCHIVE_CHANNEL_ID)
            target_channel = bot.get_channel(channel_id)
            if target_channel:
                print(f"Set default archive channel to: #{target_channel.name} (ID: {target_channel.id})", flush=True)
                if ARCHIVE_ALL_LINKS_IN_CHANNEL:
                    print(f"Auto-archiving enabled for links posted in #{target_channel.name}", flush=True)
            else:
                print(f"Warning: Could not find channel with ID: {DEFAULT_ARCHIVE_CHANNEL_ID}. Make sure the bot has access.", flush=True)
        except ValueError:
            print(f"Error: DEFAULT_ARCHIVE_CHANNEL_ID '{DEFAULT_ARCHIVE_CHANNEL_ID}' is not a valid integer.", flush=True)
    else:
        print("DEFAULT_ARCHIVE_CHANNEL_ID not set. Bot will only respond to commands or auto-archive in the channel they are issued.", flush=True)
        if ARCHIVE_ALL_LINKS_IN_CHANNEL:
             print("Warning: ARCHIVE_ALL_LINKS_IN_CHANNEL is true, but no DEFAULT_ARCHIVE_CHANNEL_ID is set. Auto-archiving will apply to any channel a link is posted in.", flush=True)

    if not KARAKEEP_API_URL or not KARAKEEP_API_KEY:
        print("Warning: Karakeep integration is disabled. Either KARAKEEP_API_URL or KARAKEEP_API_KEY is not set.", flush=True)


@bot.event
async def on_disconnect():
    global http_session
    if http_session and not http_session.closed:
        await http_session.close()
        # Do NOT set http_session = None here. Let get_http_session manage it.
        print(f'{bot.user} disconnected. HTTP session explicitly closed.', flush=True)
    else:
        print(f'{bot.user} disconnected. HTTP session already closed or not active.', flush=True)

async def archive_and_send_to_karakeep(url_to_process: str) -> tuple[bool, str]:
    # Get the http_session, ensuring it's valid or recreated
    current_http_session = await get_http_session()

    wayback_save_url = f"https://web.archive.org/save/{url_to_process}"
    archived_url = None # Initialize archived_url

    try:
        # --- Wayback Machine Archiving ---
        print(f"Attempting to archive {url_to_process} with Wayback Machine...", flush=True)
        async with current_http_session.get(wayback_save_url, allow_redirects=False, timeout=WAYBACK_MACHINE_TIMEOUT_SECONDS) as response:
            print(f"Wayback Machine response status: {response.status}", flush=True)

            if response.status == 200:
                archived_url = response.headers.get("Location", wayback_save_url)
                print(f"Wayback Machine archived (Status 200): {archived_url}", flush=True)
            elif response.status == 302:
                archived_url = response.headers.get("Location")
                if archived_url:
                    print(f"Wayback Machine archived (Status 302 Redirect): {archived_url}", flush=True)
                else:
                    return False, f"Wayback Machine returned 302 but no Location header for {url_to_process}. Unable to get archived URL."
            else:
                return False, f"Failed to archive to Wayback Machine. Unexpected status: {response.status} for {url_to_process}."

        if not archived_url:
            return False, f"Could not determine archived URL from Wayback Machine for {url_to_process}."

        # --- Karakeep Integration (only if enabled) ---
        if not KARAKEEP_API_URL or not KARAKEEP_API_KEY:
            print(f"Skipping Karakeep submission for {url_to_process}: KARAKEEP_API_URL or KARAKEEP_API_KEY not set.", flush=True)
            return True, f"Wayback Machine archived: {archived_url} (Karakeep skipped)."

        karakeep_api_endpoint = KARAKEEP_API_URL
        print(f"Submitting {archived_url} to Karakeep...", flush=True)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {KARAKEEP_API_KEY}"
        }
        payload = {
            "url": archived_url,
            "source": "discord_bot_archivebot",
            "type": "link" # ADDED THIS LINE for Karakeep API schema
        }
        async with current_http_session.post(karakeep_api_endpoint, json=payload, headers=headers, timeout=30) as response:
            karakeep_response_data = await response.json()
            if response.status in (200, 201):
                return True, f"Wayback Machine archived and Karakeep submission successful for {url_to_process}"
            else:
                return False, f"Karakeep submission failed (Status: {response.status}): {karakeep_response_data.get('error', 'Unknown error')}"

    except aiohttp.ClientConnectorError as e:
        return False, f"Connection error during web request: {e}"
    except asyncio.TimeoutError:
        return False, "Web request timed out."
    except Exception as e:
        return False, f"An unexpected error occurred during archiving/submission: {e}"

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    response_channel = message.channel
    if target_channel:
        response_channel = target_channel

    # --- Command-based archiving ---
    if message.content.startswith('!archive '):
        url_to_process = message.content[len('!archive '):].strip()
        print(f"Command-triggered URL: {url_to_process} from {message.author}", flush=True)

        # Send an initial message to indicate processing
        initial_bot_message = await response_channel.send(f"Attempting to archive and save: `{url_to_process}` (command-triggered). Please wait...")

        success, result_message = await archive_and_send_to_karakeep(url_to_process)
        if success:
            await response_channel.send(f"Successfully processed: {result_message}")
        else:
            await response_channel.send(f"Failed to process URL: {result_message}")

        # Delete the user's original message
        try:
            await message.delete()
            print(f"Deleted user message: '{message.content}' from {message.author}", flush=True)
        except discord.Forbidden:
            print(f"Error: Bot does not have permissions to delete message in channel {message.channel.name} (ID: {message.channel.id})", flush=True)
            await response_channel.send("⚠️ I don't have permission to delete messages! Please ensure I have 'Manage Messages'.")
        except discord.HTTPException as e:
            print(f"Error deleting message: {e}", flush=True)
            await response_channel.send(f"An error occurred while trying to delete the original message: {e}")
        finally:
            # Optionally delete the bot's "Please wait..." message
            try:
                await initial_bot_message.delete()
            except (discord.Forbidden, discord.HTTPException) as e:
                print(f"Warning: Could not delete bot's 'Please wait...' message: {e}", flush=True)

        return

    # --- Auto-archiving of all links ---
    if ARCHIVE_ALL_LINKS_IN_CHANNEL and (not DEFAULT_ARCHIVE_CHANNEL_ID or message.channel.id == int(DEFAULT_ARCHIVE_CHANNEL_ID)):
        urls_found = re.findall(URL_REGEX, message.content)
        if urls_found:
            for url_to_process in urls_found:
                print(f"Auto-detected URL: {url_to_process} from {message.author}", flush=True)
                if "cdn.discordapp.com" in url_to_process or "media.discordapp.net" in url_to_process:
                    print(f"Skipping Discord internal URL: {url_to_process}", flush=True)
                    continue

                # Send an initial message to indicate processing
                initial_bot_message = await response_channel.send(f"Auto-archiving detected URL: `{url_to_process}`. Please wait...")

                success, result_message = await archive_and_send_to_karakeep(url_to_process)
                if success:
                    await response_channel.send(f"Successfully auto-processed: {result_message}")
                else:
                    await response_channel.send(f"Failed to auto-process URL: {result_message}")

                # Delete the user's original message
                try:
                    await message.delete()
                    print(f"Deleted user message: '{message.content}' from {message.author}", flush=True)
                except discord.Forbidden:
                    print(f"Error: Bot does not have permissions to delete message in channel {message.channel.name} (ID: {message.channel.id})", flush=True)
                    await response_channel.send("⚠️ I don't have permission to delete messages! Please ensure I have 'Manage Messages'.")
                except discord.HTTPException as e:
                    print(f"Error deleting message: {e}", flush=True)
                    await response_channel.send(f"An error occurred while trying to delete the original message: {e}")
                finally:
                    # Optionally delete the bot's "Please wait..." message
                    try:
                        await initial_bot_message.delete()
                    except (discord.Forbidden, discord.HTTPException) as e:
                        print(f"Warning: Could not delete bot's 'Please wait...' message: {e}", flush=True)


# --- Run the bot ---
if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set.", flush=True)
        exit(1)

    bot.run(DISCORD_BOT_TOKEN)