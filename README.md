# NWS Discord Alert Bot (v3.4.0)

A Python-based Discord bot that monitors National Weather Service (NWS) Atom/CAP feeds for weather alerts and posts customizable notifications to a designated Discord channel. It includes features for user subscriptions based on location and event type, automatic role creation, and role pinging.

**(Consider adding a screenshot of an alert embed here)**

## Features

* **NWS Alert Monitoring:** Periodically fetches and parses the official NWS Atom/CAP feeds.
* **Discord Posting:** Posts new/updated/cancelled alerts as formatted embeds in a specific channel.
* **User Subscriptions:**
    * Users can subscribe to specific NWS location codes (UGC/FIPS).
    * Supports optional subscription to *specific event types* within a location (e.g., only Tornado Warnings for NYC061).
    * Commands: `!subscribe add`, `!subscribe remove`, `!subscribe list`.
* **Automatic Role Management:**
    * Automatically creates mentionable Discord roles based on subscribed location codes (e.g., `NYC061 Alerts`).
    * Assigns/removes roles to users based on their subscriptions.
    * Requires **Manage Roles** permission for the bot.
* **Role Pinging:** Mentions the relevant location role(s) when posting an alert, notifying subscribed users.
* **Configurable Filtering:** Filter alerts based on minimum Severity, Certainty, Urgency, and a list of blocked event types (configurable via `config.json` and owner commands).
* **Status & Information Commands:** `!ping`, `!status`, `!wxalerts` (lookup), `!stats` (posted alert stats), `!recent` (recently posted alerts).
* **Owner Commands:** Includes commands for manual fetching, filter management, and bot/system control (`!fetch`, `!filter`, `!shutdown`, `!restart`, `!reboot`, `!sysshutdown`).
* **Timestamped Logging:** Creates a new, uniquely named log file on each startup.
* **Error Reporting:** Reports errors to a designated Discord channel (optional) with unique IDs.
* **Automatic Changelog:** Posts a summary of changes to a designated channel on version updates.
* **Rotating Status:** Displays different activities/statuses in Discord.

## Requirements

* Python 3.10+
* External Libraries: See `requirements.txt` (`requests`, `discord.py`, `PyNaCl`).

## Setup and Installation

1.  **Clone Repository:**
    ```bash
    git clone <your-repo-url>
    cd <your-repo-name> # e.g., cd NewWeatherBot
    ```
    (Or just download the files into your `NewWeatherBot` folder).

2.  **Create Virtual Environment:**
    ```bash
    # Make sure you are using Python 3.10 or 3.11
    python3.11 -m venv new_env # Or python3 -m venv new_env
    source new_env/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure `config.json`:**
    * Copy the `config.json` template provided previously (the one *without* the `youtube` section).
    * Save it as `config.json` in the bot's directory.
    * **Edit the file** and replace **ALL** placeholder values (`YOUR_..._HERE`) with your actual information. Pay close attention to:
        * `nws_atom_url`: Set to your desired NWS feed (e.g., the US feed `https://alerts.weather.gov/cap/us.php?x=1`, or a state/county feed).
        * `discord.token`: Your secret Discord Bot Token. **Keep this secure!**
        * `discord.channel_id`: The ID of the channel where weather alerts should be posted.
        * `discord.error_channel_id`: (Optional) Channel ID for error logging.
        * `discord.changelog_channel_id`: (Optional) Channel ID for automatic update announcements.
        * `discord.owner_ids`: Your Discord User ID (allows you to use owner commands).
        * `filtering`: Adjust default alert filters if desired.
    * **Ensure the file is valid JSON** (no trailing commas, no `//` comments). Use an online JSON validator if unsure.

5.  **Discord Bot Application:**
    * Create a Bot Application in the [Discord Developer Portal](https://discord.com/developers/applications).
    * Copy the Bot Token (paste into `config.json`).
    * Enable **Privileged Gateway Intents**:
        * `PRESENCE INTENT` (Optional, might be needed for some status features or future additions)
        * `SERVER MEMBERS INTENT` (Likely needed for role assignments to work reliably)
        * `MESSAGE CONTENT INTENT` (Needed for commands)

6.  **Discord Server Setup:**
    * Invite your bot to your server using an invite link generated from the Developer Portal (make sure `bot` and `applications.commands` scopes are selected).
    * Grant the bot the necessary permissions in Server Settings -> Roles -> (Your Bot Role):
        * **Required:** `Send Messages`, `Embed Links`, **`Manage Roles`**
        * Recommended: `Read Message History` (for command context), `View Channel` (for relevant channels).
    * Make sure the bot's role is positioned **higher** in the role list than the alert roles it will create (e.g., higher than any potential `NYC061 Alerts` role).

## Usage

1.  **Activate Virtual Environment:**
    ```bash
    cd /path/to/your/NewWeatherBot
    source new_env/bin/activate
    ```
2.  **Run the Bot:**
    ```bash
    python3 DiscordWeatherBot.py
    ```
3.  **Running in Background (Optional):**
    * Use `tmux` or `screen` for detachable sessions.
    * Use `nohup python3 DiscordWeatherBot.py > output.log 2>&1 &` for simple backgrounding (check `output.log` and the script's log files for errors).
    * Set up a `systemd` service (Linux) or `launchd` agent (macOS) for robust background operation and auto-restarting.

## Commands

Use `!help` to see commands within Discord.

**General Commands:**

* `!ping`: Checks bot latency.
* `!status`: Displays current bot status and settings.
* `!subscribe add <CODE> [Event Name]`: Subscribes to alerts for a location code (e.g., `NYC061`), optionally only for a specific event (e.g., `Tornado Warning`). Creates/assigns role.
* `!subscribe remove <CODE> [Event Name]`: Removes a specific subscription.
* `!subscribe remove all`: Removes all your subscriptions.
* `!subscribe list`: Shows your current subscriptions.
* `!wxalerts <CODE1> [CODE2...]`: Looks up currently active alerts for specified codes.
* `!stats`: Shows statistics on posted alert types.
* `!recent [count]`: Shows the last `count` (default 5, max 10) posted alerts.

**Owner Commands (Hidden):**

* `!fetch`: Manually triggers an NWS alert check.
* `!filter show`: Displays current alert filtering settings.
* `!filter set <type> <value>`: Sets minimum `severity`, `certainty`, or `urgency`.
* `!filter addblock <Event Name>`: Adds an event type to the blocklist.
* `!filter rmblock <Event Name>`: Removes an event type from the blocklist.
* `!shutdown`: Stops the bot script gracefully.
* `!restart`: Stops the bot script (requires external process manager to restart).
* `!reboot`: Attempts to reboot the host machine (Requires `sudo`). **Use with extreme caution.**
* `!sysshutdown`: Attempts to shut down the host machine (Requires `sudo`). **Use with extreme caution.**

## Support

If you need help with the bot or have questions, feel free to join our support Discord server:

[Join the Support Server](https://discord.gg/Fq5zBRv7np)

You can also reach out via email: solomonder1234@gmail.com
