# -*- coding: utf-8 -*-
# Weather Alert Bot v3.4.3 (Discord Only - Whitespace/Indent Cleaned)

import requests
# import tweepy # Removed
import os
import logging
import logging.handlers
import time
import xml.etree.ElementTree as ET
import json
import random
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands, tasks
import asyncio
import subprocess
import sqlite3
import sys
import traceback
from collections import defaultdict
import uuid  # For unique error IDs
import itertools  # For status rotation
import aiohttp

# --- Fix type hints for Python 3.9+ compatibility ---
from typing import Optional, Union, List, Tuple, Dict, Set, Any

# --- Google API Imports REMOVED ---
GOOGLE_API_AVAILABLE = False

# --- Basic Setup (Logging, Config Path) ---
script_dir = os.path.dirname(os.path.abspath(__file__))
config_file = "config.json"
config_path = os.path.join(script_dir, config_file)
log_dir = os.path.join(script_dir, "logs");
os.makedirs(log_dir, exist_ok=True)

# --- LOGGING SETUP: Timestamped Files ---
startup_time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file_name = f'nws_alert_bot_{startup_time_str}.log'
log_file_path = os.path.join(log_dir, log_file_name)
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s [%(funcName)s:%(lineno)d] - %(message)s')
log_handler = logging.FileHandler(log_file_path, mode='w', encoding='utf-8')  # Use FileHandler, mode 'w'
log_handler.setFormatter(log_formatter)
console_handler = logging.StreamHandler(sys.stdout);
console_handler.setFormatter(log_formatter);
console_handler.setLevel(logging.INFO)
logger = logging.getLogger();
logger.setLevel(logging.INFO)
for h in logger.handlers[:]:
    logger.removeHandler(h)
logger.addHandler(log_handler)
logger.addHandler(console_handler)

logging.info("--- Script Started (v3.4.1 - Whitespace Cleaned) ---")
logging.info(f"Logging configured to file: {log_file_path}")

# --- Configuration Loading ---
config = {}
try:
    with open(config_path, "r", encoding='utf-8') as f:
        config = json.load(f)
    logging.info(f"Config loaded from {config_path}")
except FileNotFoundError:
    logging.warning(f"Config file '{config_path}' not found.");
    config = {}
except json.JSONDecodeError as e:
    logging.error(f"Invalid JSON in {config_path}: {e}. Fix!");
    config = {}
except Exception as e:
    logging.exception(f"Error loading config {config_path}: {e}");
    config = {}

# --- Constants & Settings ---
SCRIPT_VERSION = "3.4.1"
ATOM_NS = "{http://www.w3.org/2005/Atom}";
CAP_NS = "{urn:oasis:names:tc:emergency:cap:1.2}"
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", config.get("check_interval_seconds", 900)))
POST_DELAY_SECONDS = int(os.environ.get("POST_DELAY_SECONDS", config.get("post_delay_seconds", 10)))
USER_AGENT = os.environ.get("USER_AGENT", config.get("user_agent", f"NWSAlertBot/{SCRIPT_VERSION} (Discord; +ContactInfo)"))
DATABASE_FILE = os.path.join(script_dir, os.environ.get("DATABASE_FILE", config.get("database_file", "alerts_v3.db")))
MAX_PROCESS_PER_CYCLE = int(os.environ.get("MAX_PROCESS_PER_CYCLE", config.get("max_process_per_cycle", 50)))
DISCORD_MAX_LENGTH = 4096
MAX_LOOKUP_CODES = 10;
MAX_LOOKUP_RESULTS = 25
STATUS_ROTATION_MINUTES = int(os.environ.get("STATUS_ROTATION_MINUTES", config.get("status_rotation_minutes", 15)))
DATABASE_RETENTION_DAYS = int(os.environ.get("DATABASE_RETENTION_DAYS", config.get("database_retention_days", 30)))

# --- Filtering Settings (Globals) ---
FILTER_CONFIG = config.get("filtering", {})
SEVERITY_LEVELS = {"Unknown": 0, "Minor": 1, "Moderate": 2, "Severe": 3, "Extreme": 4}
CERTAINTY_LEVELS = {"Unknown": 0, "Unlikely": 1, "Possible": 2, "Likely": 3, "Observed": 4}
URGENCY_LEVELS = {"Unknown": 0, "Past": 1, "Future": 2, "Expected": 3, "Immediate": 4}
current_min_severity = FILTER_CONFIG.get("min_severity", "Moderate").title()
current_min_certainty = FILTER_CONFIG.get("min_certainty", "Likely").title()
current_min_urgency = FILTER_CONFIG.get("min_urgency", "Expected").title()
current_blocked_event_types = {
    event.lower() for event in FILTER_CONFIG.get("blocked_event_types", ["Test Message", "Administrative Message"])}
if current_min_severity not in SEVERITY_LEVELS:
    current_min_severity = "Moderate"
if current_min_certainty not in CERTAINTY_LEVELS:
    current_min_certainty = "Likely"
if current_min_urgency not in URGENCY_LEVELS:
    current_min_urgency = "Expected"

# --- Platform Enables & Config ---
discord_config = config.get("discord", {})
discord_enabled = True
discord_token = os.environ.get("DISCORD_TOKEN", discord_config.get("token"))
discord_channel_id = os.environ.get("DISCORD_CHANNEL_ID", discord_config.get("channel_id"))
discord_error_channel_id = os.environ.get("DISCORD_ERROR_CHANNEL_ID", discord_config.get("error_channel_id"))
discord_changelog_channel_id = os.environ.get("DISCORD_CHANGELOG_CHANNEL_ID", discord_config.get("changelog_channel_id"))
discord_owner_ids_str = os.environ.get("DISCORD_OWNER_IDS", discord_config.get("owner_ids", ""))
discord_owner_ids = set();
discord_channel_obj = None;
discord_error_channel_obj = None;
discord_changelog_channel_obj = None

if not discord_token:
    logging.critical("Discord token missing.");
    sys.exit(1)
if not discord_channel_id:
    logging.critical("Discord channel_id missing.");
    sys.exit(1)
else:
    try:
        discord_channel_id = int(discord_channel_id)
    except (ValueError, TypeError):
        logging.critical("Invalid Discord channel_id. Must be an integer.")
        sys.exit(1)

if discord_error_channel_id:
    try:
        discord_error_channel_id = int(discord_error_channel_id)
    except (ValueError, TypeError):
        logging.warning(f"Invalid Discord error_channel_id ('{discord_error_channel_id}').")
        discord_error_channel_id = None

if discord_changelog_channel_id:
    try:
        discord_changelog_channel_id = int(discord_changelog_channel_id)
    except (ValueError, TypeError):
        logging.warning(f"Invalid Discord changelog_channel_id ('{discord_changelog_channel_id}').")
        discord_changelog_channel_id = None

if discord_owner_ids_str:
    try:
        # Handle both string and list inputs
        if isinstance(discord_owner_ids_str, str):
            discord_owner_ids = {int(oid.strip()) for oid in discord_owner_ids_str.split(',') if oid.strip().isdigit()}
        elif isinstance(discord_owner_ids_str, list):
            discord_owner_ids = {int(str(oid).strip()) for oid in discord_owner_ids_str if str(oid).strip().isdigit()}
        else:
            logging.error(f"Invalid owner_ids format: {type(discord_owner_ids_str).__name__}")
            discord_owner_ids = set()
    except ValueError as e:
        logging.error(f"Invalid owner_ids: '{discord_owner_ids_str}'. Error: {e}")
        discord_owner_ids = set()
logging.info("Discord configured and enabled.")

# --- YouTube Removed ---
YOUTUBE_ENABLED = False
logging.info("YouTube functionality disabled.")

# --- NWS URL ---
nws_atom_url = os.environ.get("NWS_ATOM_URL", config.get("nws_atom_url"))
if not nws_atom_url:
    logging.critical("NWS_ATOM_URL not set. Exiting.");
    sys.exit(1)

logging.info(f"v{SCRIPT_VERSION} | Discord Enabled: Yes")
logging.info(
    f"Interval:{CHECK_INTERVAL_SECONDS}s, PostDelay:{POST_DELAY_SECONDS}s, DB:{DATABASE_FILE}, MaxProcess:{MAX_PROCESS_PER_CYCLE}, StatusRotation:{STATUS_ROTATION_MINUTES}m")
logging.info(
    f"Filters: Sev>='{current_min_severity}', Cert>='{current_min_certainty}', Urg>='{current_min_urgency}', BlockedEvents#: {len(current_blocked_event_types)}")
logging.info(f"NWS URL: {nws_atom_url}")


# --- Database Setup ---
def init_db():
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        cursor = conn.cursor()
    except Exception as e:
        logging.exception(f"DB Connect Fail {DATABASE_FILE}: {e}");
        raise
    try:
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS posted_alerts (nws_id TEXT PRIMARY KEY, first_posted_utc TEXT NOT NULL, last_updated_utc TEXT NOT NULL, discord_message_id INTEGER, twitter_tweet_id INTEGER, event_type TEXT, severity TEXT, expires_utc TEXT)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_nws_id ON posted_alerts (nws_id)')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER NOT NULL, location_code TEXT NOT NULL COLLATE NOCASE, event_type TEXT COLLATE NOCASE, subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (user_id, location_code, event_type))')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sub_location_event ON subscriptions (location_code, event_type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sub_user ON subscriptions (user_id)')
        cursor.execute("PRAGMA table_info(subscriptions)")
        columns = [c[1] for c in cursor.fetchall()]
        if 'event_type' not in columns:
            logging.warning("Adding 'event_type' column.");
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN event_type TEXT COLLATE NOCASE");
            logging.info("Column added.")
        cursor.execute('CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)')
        cursor.execute("INSERT OR IGNORE INTO bot_state (key, value) VALUES ('last_changelog_version', NULL)")
        conn.commit();
        logging.info(f"DB {DATABASE_FILE} initialized/verified.")
    except sqlite3.Error as e:
        logging.exception(f"DB init error: {e}");
        raise
    finally:
        if conn:
            conn.close()


init_db()


def get_posted_alert_info(nws_id: str) -> Optional[Dict]:
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        conn.row_factory = sqlite3.Row;
        cursor = conn.cursor();
        cursor.execute("SELECT * FROM posted_alerts WHERE nws_id = ?", (nws_id,));
        row = cursor.fetchone();
        return dict(row) if row else None
    except sqlite3.Error as e:
        logging.exception(f"DB fetch {nws_id}: {e}");
        return None
    finally:
        if conn:
            conn.close()


def record_alert_post(alert_data: dict, discord_msg_id: Optional[int], is_update: bool = False):
    now_utc = datetime.now(timezone.utc).isoformat(timespec='seconds');
    nws_id = alert_data.get("id");
    tw_id = None;
    conn = None
    if not nws_id:
        logging.error("Record alert no ID.");
        return
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        cursor = conn.cursor()
    except Exception as e:
        logging.exception(f"DB connect {nws_id}: {e}");
        return
    try:
        if is_update:
            cursor.execute('UPDATE posted_alerts SET last_updated_utc=?, discord_message_id=?, expires_utc=? WHERE nws_id=?',
                           (now_utc, discord_msg_id, alert_data.get("expires", "N/A"), nws_id));
            logging.info(f"Updated {nws_id} DB.")
        else:
            cursor.execute('INSERT OR REPLACE INTO posted_alerts VALUES (?,?,?,?,?,?,?,?)',
                           (nws_id, now_utc, now_utc, discord_msg_id, tw_id, alert_data.get("event", "N/A"),
                            alert_data.get("severity", "N/A"), alert_data.get("expires", "N/A")));
            logging.info(f"Inserted {nws_id} DB.")
        conn.commit()
    except sqlite3.Error as e:
        logging.exception(f"DB record {nws_id}: {e}")
    finally:
        if conn:
            conn.close()


def get_bot_state(key: str) -> Optional[str]:
    conn = None;
    value = None
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        cursor = conn.cursor();
        cursor.execute("SELECT value FROM bot_state WHERE key = ?", (key,));
        row = cursor.fetchone();
        value = row[0] if row else None
    except sqlite3.Error as e:
        logging.exception(f"DB get state '{key}': {e}")
    finally:
        if conn:
            conn.close()
    return value


def set_bot_state(key: str, value: Optional[str]):
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        cursor = conn.cursor();
        cursor.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", (key, value));
        conn.commit();
        logging.info(f"Set bot state '{key}' to '{str(value)[:50]}...'")
    except sqlite3.Error as e:
        logging.exception(f"DB set state '{key}': {e}")
    finally:
        if conn:
            conn.close()


def add_subscription(user_id: int, location_code: str, event_type: Optional[str] = None) -> bool:
    code = location_code.upper();
    event = event_type.strip().lower() if event_type else None;
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        cursor = conn.cursor();
        cursor.execute("INSERT OR IGNORE INTO subscriptions (user_id, location_code, event_type) VALUES (?, ?, ?)",
                       (user_id, code, event));
        conn.commit();
        logging.info(f"Sub added/ok {user_id}/{code}/'{event}'.");
        return True
    except sqlite3.Error as e:
        logging.exception(f"DB sub add {user_id}/{code}/'{event}': {e}");
        return False
    finally:
        if conn:
            conn.close()


def remove_subscription(user_id: int, location_code: str, event_type: Optional[str] = None) -> bool:
    code = location_code.upper();
    event = event_type.strip().lower() if event_type else None;
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        cursor = conn.cursor()
        if event:
            cursor.execute("DELETE FROM subscriptions WHERE user_id=? AND location_code=? AND event_type=?",
                           (user_id, code, event))
        else:
            cursor.execute("DELETE FROM subscriptions WHERE user_id=? AND location_code=? AND event_type IS NULL",
                           (user_id, code))
        rows_affected = cursor.rowcount;
        conn.commit()
        if rows_affected > 0:
            logging.info(f"Sub removed user {user_id} code {code} event '{event}'.")
        else:
            logging.info(f"No matching sub found remove user {user_id} code {code} event '{event}'.")
        return True
    except sqlite3.Error as e:
        logging.exception(f"DB sub remove {user_id}/{code}/'{event}': {e}");
        return False
    finally:
        if conn:
            try:
                conn.close()
            except sqlite3.Error as close_err:
                logging.exception(f"DB close err remove_sub: {close_err}")


def remove_all_subscriptions(user_id: int) -> bool:
    conn = None;
    count = 0
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        cursor = conn.cursor();
        cursor.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,));
        count = cursor.rowcount;
        conn.commit();
        logging.info(f"Removed all {count} subs for {user_id}.");
        return True
    except sqlite3.Error as e:
        logging.exception(f"DB remove all subs {user_id}: {e}");
        return False
    finally:
        if conn:
            conn.close()


def get_user_subscriptions(user_id: int) -> List[Tuple[str, Optional[str]]]:
    subs = [];
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        cursor = conn.cursor();
        cursor.execute(
            "SELECT location_code, event_type FROM subscriptions WHERE user_id=? ORDER BY location_code, event_type",
            (user_id,));
        subs = cursor.fetchall();
    except sqlite3.Error as e:
        logging.exception(f"DB get subs {user_id}: {e}")
    finally:
        if conn:
            conn.close()
    return subs


def get_subscribers_for_alert(alert_geocodes: Set[str], alert_event_type: str) -> Set[int]:
    if not alert_geocodes:
        return set()
    subscribers = set();
    event_lower = alert_event_type.lower();
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        cursor = conn.cursor();
        placeholders = ','.join('?' * len(alert_geocodes));
        query = f"SELECT DISTINCT user_id FROM subscriptions WHERE location_code IN ({placeholders}) AND (event_type = ? OR event_type IS NULL)";
        params = tuple(alert_geocodes) + (event_lower,);
        cursor.execute(query, params);
        subscribers = {r[0] for r in cursor.fetchall()};
        logging.debug(f"Found {len(subscribers)} subs for '{event_lower}' in {alert_geocodes}")
    except sqlite3.Error as e:
        logging.exception(f"DB get subscribers for codes {alert_geocodes}: {e}")
    finally:
        if conn:
            conn.close()
    return subscribers


def get_subscribers_for_codes(location_codes: Set[str]):  # Helper used for role mentions
    if not location_codes:
        return set()
    subscribers = set();
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        cursor = conn.cursor();
        placeholders = ','.join('?' * len(location_codes));
        query = f"SELECT DISTINCT user_id FROM subscriptions WHERE location_code IN ({placeholders})";
        cursor.execute(query, tuple(location_codes));
        subscribers = {r[0] for r in cursor.fetchall()}
    except sqlite3.Error as e:
        logging.exception(f"DB get subscribers for codes (general) {location_codes}: {e}")
    finally:
        if conn:
            conn.close()
    return subscribers


# --- Discord Bot Setup ---
intents = discord.Intents.default();
intents.message_content = True;
intents.guilds = True
bot = commands.Bot(command_prefix=commands.when_mentioned_or("!"), intents=intents, owner_ids=discord_owner_ids,
                  help_command=None)


async def check_is_owner(ctx):
    return await bot.is_owner(ctx.author)


# --- Concurrency Lock ---
alert_processing_lock = asyncio.Lock()


# --- Embed Helper Function ---
def create_embed(description: str, title: str = "", color: discord.Color = discord.Color.blue(),
                 **kwargs) -> discord.Embed:
    if not description:
        description = "No description provided.";
        color = discord.Color.light_grey()
    if len(description) > DISCORD_MAX_LENGTH:
        logging.warning(f"Embed desc truncated.");
        description = description[:DISCORD_MAX_LENGTH - 3] + "..."
    embed = discord.Embed(title=title, description=description, color=color, **kwargs);
    embed.timestamp = datetime.now(timezone.utc)
    return embed


# --- Error Reporting Helper ---
async def report_error(error_message: str, error_id: Optional[str] = None, traceback_info: Optional[str] = None) -> str:
    if error_id is None:
        error_id = uuid.uuid4().hex[:8]
    log_message = f"[Error ID: {error_id}] {error_message}";
    logging.error(log_message, exc_info=traceback_info)
    if discord_enabled and bot and discord_error_channel_id:
        global discord_error_channel_obj
        try:
            if bot.is_ready() and not discord_error_channel_obj:
                discord_error_channel_obj = bot.get_channel(discord_error_channel_id) or await bot.fetch_channel(
                    discord_error_channel_id)
            if discord_error_channel_obj:
                embed_desc = f"**Error ID:** `{error_id}`\n```\n{error_message[:1500]}\n```" + (
                    f"\n**Traceback:**\n```python\n{traceback_info[:1500]}\n```" if traceback_info else "")
                err_embed = create_embed(embed_desc, title="🚨 Bot Error", color=discord.Color.dark_red())
                await discord_error_channel_obj.send(embed=err_embed)
        except Exception as report_err:
            logging.error(f"Failed sending error report {error_id}: {report_err}")
    return error_id


# --- Changelog Data ---
CHANGELOGS = {
    "3.4.0": [  # Version number updated here
        "- **Removed YouTube integration features.**",
        "- Implemented **Timestamped Log Files**: Creates a new log file (e.g., `nws_alert_bot_YYYYMMDD_HHMMSS.log`) in the `logs` folder on each startup.",
        "- Bot's rotating status now includes the version number (e.g., `Listening to !help | v3.4.0`).",
        "- Includes all previous features (NWS Alerts, Subscriptions, Role Management, Stats/Recent commands, Filtering) and bug fixes.",
    ],
    "3.3.3": ["- Fixed various syntax errors & help command `TypeError`."]  # Example previous entry
}


# --- Custom Help Command ---
class MyHelpCommand(commands.MinimalHelpCommand):
    async def send_bot_help(self, mapping):
        embed = create_embed(description=f"Use `{self.context.prefix}help <command>` for more info.",
                            title=f"{bot.user.name} v{SCRIPT_VERSION} Commands", color=discord.Color.blurple())
        is_owner = await check_is_owner(self.context);
        cmd_mapping = defaultdict(list)
        for cmd in sorted(bot.commands, key=lambda c: c.name):
            if not cmd.hidden or is_owner:
                try:
                    can_run = await cmd.can_run(self.context)
                except Exception:
                    can_run = False
                if can_run:
                    category = "Owner Only" if any(
                        check.__qualname__ == check_is_owner.__qualname__ for check in cmd.checks) else "General"
                    if group := cmd.full_parent_name:
                        category = f"Group: !{group.title()}"
                    cmd_mapping[category].append(cmd)
        for category, command_list in cmd_mapping.items():
            signatures = [f"`{self.get_command_signature(c)}`\n{c.short_doc or 'No description'}" for c in
                          command_list]
            if signatures:
                embed.add_field(name=category, value="\n".join(signatures), inline=False)
        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command):
        embed = create_embed(title=f"`{self.get_command_signature(command)}`",
                            description=command.help or command.short_doc or "N/A", color=discord.Color.green())
        if command.aliases:
            embed.add_field(name="Aliases", value=", ".join(f"`{alias}`" for alias in command.aliases), inline=False)
        await self.get_destination().send(embed=embed)

    async def send_group_help(self, group):
        embed = create_embed(title=f"Group: `{self.get_command_signature(group)}`",
                            description=group.help or group.short_doc or "N/A", color=discord.Color.dark_green())
        if group.aliases:
            embed.add_field(name="Aliases", value=", ".join(f"`{alias}`" for alias in group.aliases), inline=False)
        filtered_commands = await self.filter_commands(group.commands, sort=True);
        is_owner = await check_is_owner(self.context)
        subcommands = [f"`{self.get_command_signature(cmd)}` - {cmd.short_doc or 'N/A'}" for cmd in
                       filtered_commands if not cmd.hidden or is_owner]
        if subcommands:
            embed.add_field(name="Subcommands", value="\n".join(subcommands), inline=False)
        await self.get_destination().send(embed=embed)


bot.help_command = MyHelpCommand()

# --- Discord Commands ---
@bot.command(name='ping', short_doc="Checks bot latency.")
async def ping(ctx):
    latency_ms = round(bot.latency * 1000);
    await ctx.send(embed=create_embed(f'Pong! Latency: {latency_ms}ms', title="🏓 Ping", color=discord.Color.green()));
    logging.info(f"Cmd !ping by {ctx.author}. Latency: {latency_ms}ms")


@bot.command(name='status', short_doc="Displays current bot status.")
async def status(ctx):
    db_count = 0;
    sub_count = 0;
    err_msg = None;
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        cursor = conn.cursor();
        cursor.execute("SELECT COUNT(*) FROM posted_alerts");
        db_count = cursor.fetchone()[0];
        cursor.execute("SELECT COUNT(*) FROM subscriptions");
        sub_count = cursor.fetchone()[0];
        conn.close()
    except Exception as e:
        logging.error(f"DB count error: {e}");
        db_count = "Err";
        sub_count = "Err";
        err_msg = f"DB Error: {e}"
    status_lines = [f"NWS Alert Bot v{SCRIPT_VERSION}.", f"Feed: `{nws_atom_url}`",
                    f"Interval: `{CHECK_INTERVAL_SECONDS}`s | Post Delay: `{POST_DELAY_SECONDS}`s.",
                    f"Discord: `On`", f"DB Alerts: `{db_count}` | DB Subs: `{sub_count}`"]
    if err_msg:
        status_lines.append(f"DB Status: `{err_msg}`")

    def format_task_status(task, name):
        if task and task.is_running():
            next_run = task.next_iteration;
            return f"{name}: Running ✅" + (
                f" (~{int((next_run - datetime.now(timezone.utc)).total_seconds() / 60)}m next)" if next_run else " (Next N/A)")
        else:
            return f"{name}: Not Running ❌"

    status_lines.append(format_task_status(check_alerts_task, "Alert Task"))
    status_lines.append(format_task_status(cleanup_db_task, "Cleanup Task"))
    status_lines.append(format_task_status(change_status_task, "Status Task"))
    # Removed YouTube task status line
    await ctx.send(embed=create_embed("\n".join(status_lines), title="📊 Bot Status", color=discord.Color.blurple()))
    logging.info(f"Cmd !status by {ctx.author}")


@bot.group(name='subscribe', aliases=['sub'], invoke_without_command=True)
@commands.guild_only()
async def subscribe_group(ctx):
    """Manage alert subscriptions (e.g., !sub add NYC061 [Tornado Warning])."""
    await ctx.send_help(ctx.command)


@subscribe_group.command(name='add', help="Subscribe. Usage: !sub add <CODE> [Event Name]")
@commands.guild_only()
@commands.bot_has_permissions(manage_roles=True)
async def sub_add(ctx, location_code: str, *, event_type: Optional[str] = None):
    code = location_code.upper().strip();
    event_db = event_type.strip().lower() if event_type else None
    if not code:
        await ctx.send(embed=create_embed("Provide code.", color=discord.Color.orange()));
        return
    role_name = f"{code} Alerts";
    role = discord.utils.get(ctx.guild.roles, name=role_name);
    role_created = False;
    role_assigned = False;
    db_added = False;
    role_error = None;
    bot_top_role_pos = ctx.guild.me.top_role.position
    if not role:
        try:
            role = await ctx.guild.create_role(name=role_name, mentionable=True,
                                              reason=f"Alert role by {ctx.author}");
            logging.info(f"Created role '{role_name}'");
            role_created = True;
            await asyncio.sleep(0.5)
        except discord.Forbidden:
            role_error = "Bot lacks create role permission.";
            logging.error(role_error)
        except Exception as e:
            role_error = f"Failed role create: {e}";
            logging.exception(role_error)
    if role and role.position >= bot_top_role_pos:
        role_error = "Bot role not high enough.";
        logging.warning(role_error + f" Role:{role.id}, BotTop:{ctx.guild.me.top_role.id}")
    if role and not role_error:
        if add_subscription(ctx.author.id, code, event_db):
            db_added = True
            if role not in ctx.author.roles:
                try:
                    await ctx.author.add_roles(role, reason=f"Subscribed via bot");
                    role_assigned = True;
                    logging.info(f"Assigned '{role_name}' to {ctx.author}")
                except discord.Forbidden:
                    role_error = "Bot lacks assign role permission.";
                    logging.error(role_error);
                    remove_subscription(ctx.author.id, code, event_db)
                except Exception as e:
                    role_error = f"Err assign role: {e}";
                    logging.exception(role_error);
                    remove_subscription(ctx.author.id, code, event_db)
            else:
                role_assigned = True
        else:
            role_error = "DB error."
    title = "Sub Added" if db_added else "Sub Failed";
    color = discord.Color.green() if db_added else discord.Color.red();
    desc = f"Sub for **{code}**" + (f" (`{event_type or 'All Events'}`)" if db_added else "") + (
        " added." if db_added else f" failed: {role_error or 'Unknown'}");
    if role_created:
        desc += "\n🆕 Role created!"
    if role_assigned and db_added:
        desc += "\n🔔 Role assigned!"
        desc += f"\n✅ Role `{role_name}` assigned."
    elif role and not role_error and db_added and not role_assigned:
        desc += f"\n⚠️ Role exists but couldn't assign."
    elif role_error:
        desc += f"\n❌ Role Error: {role_error}"
    await ctx.send(embed=create_embed(desc, title=title, color=color))


@subscribe_group.command(name='remove', aliases=['rm', 'unsub'],
                       help="Unsubscribe. Usage: !sub rm <CODE> [Event Name], or !sub rm all")
@commands.guild_only()
@commands.bot_has_permissions(manage_roles=True)
async def sub_remove(ctx, location_code: str, *, event_type: Optional[str] = None):
    code_raw = location_code.strip();
    event = event_type.strip() if event_type else None
    if not code_raw:
        await ctx.send(embed=create_embed("Provide code or 'all'.", color=discord.Color.orange()));
        return
    bot_top_role_pos = ctx.guild.me.top_role.position
    removed_subs = [];
    failed_subs = [];
    role_removal_errors = []
    if code_raw.lower() == 'all' and event is None:  # Unsub ALL
        current_subs = get_user_subscriptions(ctx.author.id)
        if not current_subs:
            await ctx.send(embed=create_embed("No subscriptions.", color=discord.Color.orange()));
            return
        if remove_all_subscriptions(ctx.author.id):
            removed_subs.append("`all`");
            loc_roles_to_check = {loc for loc, _ in current_subs}
            for loc_code in loc_roles_to_check:
                role = discord.utils.get(ctx.guild.roles, name=f"{loc_code} Alerts")
                if role and role in ctx.author.roles and role.position < bot_top_role_pos:
                    try:
                        await ctx.author.remove_roles(role, reason="Unsub all")
                    except Exception as e:
                        role_removal_errors.append(f"`{role.name}` ({e})")
                elif role and role in ctx.author.roles:
                    role_removal_errors.append(f"`{role.name}` (Bot role low)")
        else:
            failed_subs.append("`all` (DB Error)")
    else:  # Unsub specific
        code = code_raw.upper();
        event_db = event.lower() if event else None
        if remove_subscription(ctx.author.id, code, event_db):
            removed_subs.append(f"`{code}`" + (f" (`{event or 'All Events'}`)"))
            remaining = [sub_code for sub_code, _ in get_user_subscriptions(ctx.author.id) if sub_code == code]
            if not remaining:  # If no subs left for this code, try removing role
                role = discord.utils.get(ctx.guild.roles, name=f"{code} Alerts")
                if role and role in ctx.author.roles and role.position < bot_top_role_pos:
                    try:
                        await ctx.author.remove_roles(role, reason=f"Unsub last {code}")
                    except Exception as e:
                        role_removal_errors.append(f"`{role.name}` ({e})")
                elif role and role in ctx.author.roles:
                    role_removal_errors.append(f"`{role.name}` (Bot role low)")
        else:
            failed_subs.append(f"`{code}`" + (f" (`{event or 'All Events'}`)" + " (Not subbed?)"))
    resp_parts = []
    if removed_subs:
        resp_parts.append(f"🗑️ Unsubscribed: {', '.join(removed_subs)}")
    if failed_subs:
        resp_parts.append(f"⚠️ Failed/Not Subbed: {', '.join(failed_subs)}")
    if role_removal_errors:
        resp_parts.append(f"❌ Role Errors: {', '.join(role_removal_errors)}")
    await ctx.send(embed=create_embed("\n".join(resp_parts) if resp_parts else "No changes/Not subbed.",
                                     title="Unsubscribe Results"))


@subscribe_group.command(name='list', aliases=['show', 'mine'])
async def sub_list(ctx):
    """Lists your current alert subscriptions."""
    subs = get_user_subscriptions(ctx.author.id)
    if subs:
        sub_lines = [f"- `{loc}`" + (f" (`{evt}`)" if evt else " (All)") for loc, evt in sorted(subs)];
        await ctx.send(embed=create_embed("\n".join(sub_lines), title="📋 My Subscriptions"))
    else:
        await ctx.send(embed=create_embed("No subscriptions.", title="📋 My Subscriptions",
                                         color=discord.Color.orange()))


@bot.command(name='fetch', short_doc="Manually fetch NWS alerts (Owner Only).")
@commands.check(check_is_owner)
async def fetch(ctx):
    logging.info(f"Manual fetch by owner {ctx.author} ({ctx.author.id})")
    await ctx.send(embed=create_embed("Manual fetch triggered...", title="⚙️ Manual Fetch", color=discord.Color.gold()))
    if alert_processing_lock.locked():
        await ctx.send(embed=create_embed("Processing ongoing.", color=discord.Color.orange()));
        logging.warning(f"Manual fetch by {ctx.author} while locked.");
        return
    try:
        processed_count = await process_new_alerts()
        await ctx.send(
            embed=create_embed(f"✅ Fetch complete. Processed {processed_count} new/updated alerts.",
                              title="⚙️ Manual Fetch Result", color=discord.Color.green()));
        logging.info(f"Manual fetch completed. Processed {processed_count}.")
    except Exception as e:
        logging.exception(f"Manual fetch error by {ctx.author}: {e}");
        error_id = await report_error(f"Manual fetch failed: {e}", traceback_info=traceback.format_exc());
        await ctx.send(
            embed=create_embed(f"❌ Error during fetch. Report ID: `{error_id}`", title="⚙️ Manual Fetch Error",
                              color=discord.Color.red()))


@bot.command(name='shutdown', hidden=True, short_doc="Stops the bot script (Owner Only).")
@commands.check(check_is_owner)
async def shutdown(ctx):
    logging.warning(f"Shutdown cmd from owner {ctx.author} ({ctx.author.id}).")
    await ctx.send(embed=create_embed("Shutting down bot script...", title="🛑 Bot Shutdown",
                                     color=discord.Color.orange()))
    tasks_cancelled = []
    if check_alerts_task and check_alerts_task.is_running():
        check_alerts_task.cancel();
        tasks_cancelled.append("Check");
    if cleanup_db_task and cleanup_db_task.is_running():
        cleanup_db_task.cancel();
        tasks_cancelled.append("Cleanup");
    if change_status_task and change_status_task.is_running():
        change_status_task.cancel();
        tasks_cancelled.append("Status");
    # No YT task to cancel
    if tasks_cancelled:
        logging.info(f"Cancelled tasks: {', '.join(tasks_cancelled)}");
        await asyncio.sleep(1)
    logging.info("Closing bot connection...");
    await ctx.send(embed=create_embed("Goodbye!", title="🛑 Bot Shutdown Complete", color=discord.Color.dark_grey()));
    await bot.close();
    print("Bot closed via !shutdown.")


@bot.command(name='restart', hidden=True, short_doc="Stops bot for external restart (Owner Only).")
@commands.check(check_is_owner)
async def restart(ctx):
    logging.warning(f"Restart cmd from owner {ctx.author} ({ctx.author.id}).")
    await ctx.send(embed=create_embed("Attempting restart...\n(External tool must restart script)",
                                     title="🔄 Bot Restart", color=discord.Color.orange()))
    tasks_cancelled = []
    if check_alerts_task and check_alerts_task.is_running():
        check_alerts_task.cancel();
        tasks_cancelled.append("Check");
    if cleanup_db_task and cleanup_db_task.is_running():
        cleanup_db_task.cancel();
        tasks_cancelled.append("Cleanup");
    if change_status_task and change_status_task.is_running():
        change_status_task.cancel();
        tasks_cancelled.append("Status");
    # No YT task to cancel
    if tasks_cancelled:
        logging.info(f"Cancelled tasks: {', '.join(tasks_cancelled)}");
        await asyncio.sleep(1)
    logging.info("Closing connection for restart...");
    await bot.close();
    print("Bot closed via !restart.")


@bot.command(name='reboot', hidden=True, short_doc="Reboots host machine (Owner Only - RISKY).")
@commands.check(check_is_owner)
async def reboot_system(ctx):
    logging.warning(f"SYS REBOOT by owner {ctx.author} ({ctx.author.id}).")
    await ctx.send(embed=create_embed("Attempting **host reboot**. Needs `sudo`.", title="🚨 System Reboot 🚨",
                                     color=discord.Color.dark_red()))
    try:
        result = subprocess.run(['sudo', 'reboot'], check=False, capture_output=True, text=True, timeout=15)
    except Exception as e:
        logging.exception(f"Reboot exception: {e}");
        error_id = await report_error(f"Reboot failed: {e}", traceback_info=traceback.format_exc());
        await ctx.send(
            embed=create_embed(f"Reboot error (ID: `{error_id}`).\n`{type(e).__name__}: {e}`", title="❌ Reboot Error",
                              color=discord.Color.red()));
        return
    log_msg = f"RC={result.returncode}, Out={result.stdout[:100]}, Err={result.stderr[:200]}";
    if result.returncode == 0:
        logging.info(f"Reboot success? {log_msg}")
    else:
        logging.error(f"Reboot failed. {log_msg}");
        await ctx.send(
            embed=create_embed(f"Reboot fail (RC {result.returncode}).\n```\n{result.stderr or 'N/A'}\n```",
                              title="❌ Reboot Failed", color=discord.Color.red()))


@bot.command(name='sysshutdown', hidden=True, short_doc="Shuts down host machine (Owner Only - RISKY).")
@commands.check(check_is_owner)
async def shutdown_system(ctx):
    logging.warning(f"SYS SHUTDOWN by owner {ctx.author} ({ctx.author.id}).")
    await ctx.send(embed=create_embed("Attempting **host shutdown NOW**. Needs `sudo`.", title="🚨 System Shutdown 🚨",
                                     color=discord.Color.dark_red()))
    try:
        result = subprocess.run(['sudo', 'shutdown', 'now'], check=False, capture_output=True, text=True, timeout=15)
    except Exception as e:
        logging.exception(f"Shutdown exception: {e}");
        error_id = await report_error(f"Sys Shutdown failed: {e}", traceback_info=traceback.format_exc());
        await ctx.send(
            embed=create_embed(f"Shutdown error (ID: `{error_id}`).\n`{type(e).__name__}: {e}`",
                              title="❌ Shutdown Error", color=discord.Color.red()));
        return
    log_msg = f"RC={result.returncode}, Out={result.stdout[:100]}, Err={result.stderr[:200]}"
    if result.returncode == 0:
        logging.info(f"Shutdown success? {log_msg}")
    else:
        logging.error(f"Shutdown failed. {log_msg}");
        await ctx.send(
            embed=create_embed(f"Shutdown fail (RC {result.returncode}).\n```\n{result.stderr or 'N/A'}\n```",
                              title="❌ Shutdown Failed", color=discord.Color.red()))


@bot.group(name='filter', invoke_without_command=True, short_doc="Manage alert filters (Owner Only).")
@commands.check(check_is_owner)
async def filter_group(ctx):
    await ctx.send_help(ctx.command)


@filter_group.command(name='show', short_doc="Shows current filter settings.")
@commands.check(check_is_owner)
async def show_filters(ctx):
    global current_min_severity, current_min_certainty, current_min_urgency, current_blocked_event_types
    lines = [f"**Current Filters:**", f"- Min Severity: `{current_min_severity}`",
             f"- Min Certainty: `{current_min_certainty}`", f"- Min Urgency: `{current_min_urgency}`",
             f"- Blocked Events ({len(current_blocked_event_types)}): `{'`, `'.join(sorted(list(current_blocked_event_types))) if current_blocked_event_types else 'None'}`"]
    await ctx.send(embed=create_embed("\n".join(lines), title="🔎 Alert Filters", color=discord.Color.info()))


@filter_group.command(name='set', short_doc="Set filter level (severity/certainty/urgency).")
@commands.check(check_is_owner)
async def set_filter(ctx, filter_type: str.lower, *, value: str):
    global current_min_severity, current_min_certainty, current_min_urgency
    value_title = value.title();
    updated = False
    if filter_type == 'severity':
        if value_title in SEVERITY_LEVELS:
            current_min_severity = value_title;
            updated = True
        else:
            await ctx.send(embed=create_embed(f"Invalid severity. Options: {', '.join(SEVERITY_LEVELS.keys())}",
                              color=discord.Color.red()));
            return
    elif filter_type == 'certainty':
        if value_title in CERTAINTY_LEVELS:
            current_min_certainty = value_title;
            updated = True
        else:
            await ctx.send(embed=create_embed(f"Invalid certainty. Options: {', '.join(CERTAINTY_LEVELS.keys())}",
                              color=discord.Color.red()));
            return
    elif filter_type == 'urgency':
        if value_title in URGENCY_LEVELS:
            current_min_urgency = value_title;
            updated = True
        else:
            await ctx.send(embed=create_embed(f"Invalid urgency. Options: {', '.join(URGENCY_LEVELS.keys())}",
                              color=discord.Color.red()));
            return
    else:
        await ctx.send(embed=create_embed("Invalid type. Use 'severity', 'certainty', or 'urgency'.",
                          color=discord.Color.red()));
        return
    if updated:
        logging.warning(f"Filter '{filter_type}' set to '{value_title}' by {ctx.author}.");
        await ctx.send(embed=create_embed(f"✅ Min {filter_type} updated to `{value_title}`.",
                          color=discord.Color.green()));
        await show_filters(ctx)


@filter_group.command(name='addblock', short_doc="Add event type to blocklist.")
@commands.check(check_is_owner)
async def add_block(ctx, *, event_name: str):
    global current_blocked_event_types
    event_lower = event_name.lower().strip();
    if not event_lower:
        await ctx.send(embed=create_embed("Provide event name.", color=discord.Color.orange()));
        return
    if event_lower not in current_blocked_event_types:
        current_blocked_event_types.add(event_lower);
        logging.warning(f"'{event_name}' added to blocklist by {ctx.author}.");
        await ctx.send(embed=create_embed(f"✅ `{event_name}` added to blocklist.", color=discord.Color.green()));
        await show_filters(ctx)
    else:
        await ctx.send(embed=create_embed(f"`{event_name}` already blocked.", color=discord.Color.orange()))


@filter_group.command(name='removeblock', aliases=['rmblock'], short_doc="Remove event type from blocklist.")
@commands.check(check_is_owner)
async def remove_block(ctx, *, event_name: str):
    global current_blocked_event_types
    event_lower = event_name.lower().strip();
    if not event_lower:
        await ctx.send(embed=create_embed("Provide event name.", color=discord.Color.orange()));
        return
    if event_lower in current_blocked_event_types:
        current_blocked_event_types.remove(event_lower);
        logging.warning(f"'{event_name}' removed from blocklist by {ctx.author}.");
        await ctx.send(embed=create_embed(f"✅ `{event_name}` removed from blocklist.",
                          color=discord.Color.green()));
        await show_filters(ctx)
    else:
        await ctx.send(embed=create_embed(f"`{event_name}` not found in blocklist.",
                          color=discord.Color.orange()))


@bot.command(name='wxalerts', short_doc="Look up active alerts for UGC/FIPS codes.")
async def wxalerts(ctx, *, location_codes: str):
    # ... (Function remains unchanged) ...
    codes_to_check = {code.strip().upper() for code in location_codes.split() if code.strip()}
    if not codes_to_check:
        await ctx.send(embed=create_embed("Provide UGC/FIPS codes.", title="⚠️ Missing Codes",
                          color=discord.Color.orange()));
        return
    if len(codes_to_check) > MAX_LOOKUP_CODES:
        await ctx.send(embed=create_embed(f"Max {MAX_LOOKUP_CODES} codes.", title="⚠️ Too Many Codes",
                          color=discord.Color.orange()));
        return
    await ctx.send(embed=create_embed(f"Lookup for: `{', '.join(codes_to_check)}`...", title="🔍 Alert Lookup",
                      color=discord.Color.gold()))
    alerts = await asyncio.to_thread(get_nws_alerts)
    if alerts is None:
        await ctx.send(embed=create_embed("Failed fetch.", title="❌ Lookup Failed", color=discord.Color.red()))
        return
    if not alerts:
        await ctx.send(embed=create_embed(f"No active alerts.", title="✅ Lookup Complete",
                          color=discord.Color.green()))
        return
    matching_alerts = []
    processed_ids = set()
    for alert_entry in alerts:
        alert_data = extract_alert_data(alert_entry)
        if not alert_data or alert_data['id'] in processed_ids:
            continue
        alert_geocodes = set()
        geocode_data = alert_data.get("geocode")
        if isinstance(geocode_data, dict):
            if "UGC" in geocode_data:
                alert_geocodes.update(g.strip().upper() for g in geocode_data["UGC"].split() if g.strip())
            if "FIPS6" in geocode_data:
                alert_geocodes.update(g.strip().upper() for g in geocode_data["FIPS6"].split() if g.strip())
        if any(code in alert_geocodes for code in codes_to_check):
            event_lower = alert_data.get("event", "").lower()
            min_sev_lvl = SEVERITY_LEVELS.get(current_min_severity, 0)
            min_cert_lvl = CERTAINTY_LEVELS.get(current_min_certainty, 0)
            min_urg_lvl = URGENCY_LEVELS.get(current_min_urgency, 0)
            severity_level = SEVERITY_LEVELS.get(alert_data.get("severity", "Unknown"), 0)
            certainty_level = CERTAINTY_LEVELS.get(alert_data.get("certainty", "Unknown"), 0)
            urgency_level = URGENCY_LEVELS.get(alert_data.get("urgency", "Unknown"), 0)
            if (event_lower not in current_blocked_event_types and 
                severity_level >= min_sev_lvl and 
                certainty_level >= min_cert_lvl and 
                urgency_level >= min_urg_lvl):
                matching_alerts.append(alert_data)
                processed_ids.add(alert_data['id'])
            else:
                logging.debug(f"Lookup skipped {alert_data['id']} (filters).")
    if not matching_alerts:
        await ctx.send(embed=create_embed(f"No active alerts matching codes & filters.", title="✅ Lookup Complete",
                          color=discord.Color.green()));
        return
    logging.info(f"Found {len(matching_alerts)} alerts for lookup by {ctx.author}. Codes: {codes_to_check}")
    matching_alerts.sort(key=lambda x: (SEVERITY_LEVELS.get(x.get('severity', 'Unknown'), 0),
                                         x.get('effective', '')), reverse=True)
    if len(matching_alerts) > MAX_LOOKUP_RESULTS:
        logging.warning(f"Truncating !wxalerts results to {MAX_LOOKUP_RESULTS}");
        matching_alerts = matching_alerts[:MAX_LOOKUP_RESULTS]

    def format_t(ts):
        return f"<t:{int(datetime.fromisoformat(ts).timestamp())}:R>" if ts and ts != 'N/A' else 'N/A'

    current_desc = "";
    embed_count = 0;
    msg_count = 0;
    MAX_ALERTS_PER_MSG = 5
    for alert in matching_alerts:
        if embed_count >= MAX_ALERTS_PER_MSG:
            msg_count += 1;
            title_part = f"Active Alerts for {', '.join(codes_to_check)} (Part {msg_count})";
            await ctx.send(embed=create_embed(current_desc, title=title_part));
            current_desc = "";
            embed_count = 0;
            await asyncio.sleep(1)
        title = alert.get('title', 'N/A');
        event = alert.get('event', 'N/A');
        expires_fmt = format_t(alert.get('expires'))
        current_desc += f"**• {event}:** {title} (Expires: {expires_fmt})\n";
        embed_count += 1
    if current_desc:
        msg_count += 1;
        part_str = f"(Part {msg_count})" if msg_count > 1 or len(matching_alerts) > MAX_ALERTS_PER_MSG else "";
        await ctx.send(embed=create_embed(current_desc, title=f"Active Alerts for {', '.join(codes_to_check)} {part_str}"))


@bot.command(name='post', hidden=True, short_doc="Make bot say something (Owner Only).")
@commands.check(check_is_owner)
async def post_message(ctx, *, message_content: str):
    if discord_channel_obj:
        try:
            # Fixed accidental line break in variable name
            if len(message_content) > 2000:
                await ctx.send(embed=create_embed("Msg too long (>2000).", color=discord.Color.orange()))
                return
            await discord_channel_obj.send(message_content)
            await ctx.message.add_reaction('✅')
            logging.info(f"Owner {ctx.author} posted msg via !post.")
        except discord.Forbidden:
            await ctx.send(embed=create_embed("Error: Bot lacks permission.", color=discord.Color.red()))
        except Exception as e:
            logging.exception(f"Error in !post: {e}")
            error_id = await report_error(f"!post fail: {e}", traceback_info=traceback.format_exc())
            await ctx.send(embed=create_embed(f"Failed. Error ID: `{error_id}`", color=discord.Color.red()))
    else:
        await ctx.send(embed=create_embed("Alert channel not found.", color=discord.Color.red()))


@bot.command(name='announce', hidden=True, short_doc="Sends announcement embed (Owner Only).")
@commands.check(check_is_owner)
async def make_announcement(ctx, *, content: str):
    if not discord_channel_obj:
        await ctx.send(embed=create_embed("Alert channel not found.", color=discord.Color.red()));
        return
    allowed_mentions = discord.AllowedMentions.none();
    mention_text = None
    if '@everyone' in content:
        allowed_mentions.everyone = True;
        mention_text = '@everyone'
    if '@here' in content:
        allowed_mentions.here = True;
        mention_text = '@here'
    embed = create_embed(description=content, title="📢 Announcement", color=discord.Color.gold());
    embed.set_author(name=f"Sent by {ctx.author.display_name}",
                     icon_url=ctx.author.display_avatar.url if ctx.author.display_avatar else None)
    try:
        await discord_channel_obj.send(content=mention_text, embed=embed, allowed_mentions=allowed_mentions);
        await ctx.message.add_reaction('✅');
        logging.info(f"Sent announcement by {ctx.author}: {content[:100]}...")
    except discord.Forbidden:
        await ctx.send(embed=create_embed("Error: Bot lacks permission.", color=discord.Color.red()))
    except Exception as e:
        logging.exception(f"Error in !announce: {e}");
        error_id = await report_error(f"!announce fail: {e}", traceback_info=traceback.format_exc());
        await ctx.send(embed=create_embed(f"Failed. Error ID: `{error_id}`", color=discord.Color.red()))
# YouTube commands removed
@bot.command(name='stats', short_doc="Shows posted alert statistics.")
async def alert_stats(ctx):
    stats_data = {};
    total_count = 0;
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        cursor = conn.cursor();
        cursor.execute("SELECT event_type, COUNT(*) FROM posted_alerts GROUP BY event_type ORDER BY COUNT(*) DESC");
        stats_data = {row[0] if row[0] else 'N/A': row[1] for row in cursor.fetchall()};
        cursor.execute("SELECT COUNT(*) FROM posted_alerts");
        total_count = cursor.fetchone()[0];
    except Exception as e:
        logging.exception(f"Error getting stats: {e}");
        error_id = await report_error(f"Stats DB error: {e}", traceback_info=traceback.format_exc());
        await ctx.send(embed=create_embed(f"Error fetching stats. ID: `{error_id}`", color=discord.Color.red()));
        return
    finally:
        if conn:
            conn.close()
    if not stats_data:
        await ctx.send(embed=create_embed("No stats yet.", title="📊 Alert Stats"));
        return
    desc = f"**Total Alerts Recorded:** {total_count}\n\n**Breakdown by Type:**\n";
    lines = [f"- `{event}`: {count}" for event, count in stats_data.items()]
    desc += "\n".join(lines[:20]);
    if len(lines) > 20:
        desc += "\n..."
    await ctx.send(embed=create_embed(desc, title="📊 Alert Statistics"))


@bot.command(name='recent', short_doc="Shows recently posted alerts.")
async def recent_alerts(ctx, count: int = 5):
    if not 1 <= count <= 10:
        await ctx.send(embed=create_embed("Count 1-10.", color=discord.Color.orange()));
        return
    alerts = [];
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE);
        conn.row_factory = sqlite3.Row;
        cursor = conn.cursor();
        cursor.execute("SELECT nws_id, first_posted_utc, event_type FROM posted_alerts ORDER BY first_posted_utc DESC LIMIT ?",
                       (count,));
        alerts = [dict(row) for row in cursor.fetchall()];
    except Exception as e:
        logging.exception(f"Error getting recent: {e}");
        error_id = await report_error(f"Recent DB error: {e}", traceback_info=traceback.format_exc());
        await ctx.send(embed=create_embed(f"Error fetching recent. ID: `{error_id}`",
                          color=discord.Color.red()));
        return
    finally:
        if conn:
            conn.close()
    if not alerts:
        await ctx.send(embed=create_embed("No recent alerts found.", title="🕒 Recent Alerts"));
        return
    desc_lines = []

    def format_t(ts):
        return f"<t:{int(datetime.fromisoformat(ts).timestamp())}:R>" if ts else 'Invalid Time'

    for alert in alerts:
        ts_fmt = format_t(alert.get('first_posted_utc'));
        desc_lines.append(
            f"- `{alert.get('event_type', 'N/A')}` ({ts_fmt}) - ID: `{alert.get('nws_id', 'N/A')[-10:]}...`")
    await ctx.send(embed=create_embed("\n".join(desc_lines), title=f"🕒 Last {len(alerts)} Recorded Alerts"))


# --- Event Handlers ---
@bot.event
async def on_ready():
    logging.info(f'Discord bot logged in as {bot.user.name} ({bot.user.id})');
    print(f'Discord bot logged in as {bot.user.name}')
    global discord_channel_obj, discord_error_channel_obj, discord_changelog_channel_obj
    # Fetch Discord channel objects
    if discord_channel_id:
        try:
            discord_channel_obj = bot.get_channel(discord_channel_id) or await bot.fetch_channel(
                discord_channel_id)
        except Exception as e:
            logging.error(f"Failed fetch alert channel {discord_channel_id}: {e}")
        if not discord_channel_obj:
            logging.error(f"Could not find alert channel: {discord_channel_id}")
    if discord_error_channel_id:
        try:
            discord_error_channel_obj = bot.get_channel(discord_error_channel_id) or await bot.fetch_channel(
                discord_error_channel_id)
        except Exception as e:
            logging.error(f"Failed fetch error channel {discord_error_channel_id}: {e}")
        if not discord_error_channel_obj:
            logging.warning(f"Could not find error channel: {discord_error_channel_id}")
        else:
            await discord_error_channel_obj.send(
                embed=create_embed(f"Bot v{SCRIPT_VERSION} connected.", title="✅ Bot Online",
                                  color=discord.Color.green()))
    if discord_changelog_channel_id:
        try:
            discord_changelog_channel_obj = bot.get_channel(
                discord_changelog_channel_id) or await bot.fetch_channel(discord_changelog_channel_id)
        except Exception as e:
            logging.error(f"Failed fetch changelog channel {discord_changelog_channel_id}: {e}")
        if not discord_changelog_channel_obj:
            logging.warning(f"Could not find changelog channel: {discord_changelog_channel_id}.")

    # --- Post Changelog If New Version ---
    if discord_changelog_channel_id and discord_changelog_channel_obj:
        try:
            last_posted_version = get_bot_state('last_changelog_version')
            if SCRIPT_VERSION != last_posted_version:
                logging.info(f"New version ({SCRIPT_VERSION} vs {last_posted_version}). Posting changelog.")
                changelog_text = "\n".join(
                    [f"- {item}" for item in CHANGELOGS.get(SCRIPT_VERSION, ["No specific changes listed for this version."])])
                await discord_changelog_channel_obj.send(
                    embed=create_embed(changelog_text, title=f"📢 Changelog v{SCRIPT_VERSION}", color=discord.Color.gold()))
                set_bot_state('last_changelog_version', SCRIPT_VERSION)
        except Exception as e:
            logging.exception(f"Failed post changelog: {e}")

async def setup_tasks():
    global check_alerts_task, cleanup_db_task, change_status_task
    check_alerts_task = bot.loop.create_task(check_alerts())
    cleanup_db_task = bot.loop.create_task(cleanup_database())
    change_status_task = bot.loop.create_task(change_status())

async def fetch_nws_feed():
    """Fetches alerts from NWS feed URL."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(nws_atom_url, headers={'User-Agent': USER_AGENT}) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    logging.error(f"NWS fetch failed: {response.status}")
                    return None
    except Exception as e:
        logging.error(f"NWS fetch error: {e}")
        return None

def extract_alert_data(entry) -> Optional[Dict]:
    """Extract relevant data from an alert entry."""
    try:
        alert_id = entry.find(f'./{ATOM_NS}id').text
        if not alert_id:
            return None
            
        cap_event = entry.find(f'.//{CAP_NS}event')
        cap_severity = entry.find(f'.//{CAP_NS}severity')
        cap_certainty = entry.find(f'.//{CAP_NS}certainty')
        cap_urgency = entry.find(f'.//{CAP_NS}urgency')
        cap_expires = entry.find(f'.//{CAP_NS}expires')
        
        geocodes = {}
        for code in entry.findall(f'.//{CAP_NS}geocode'):
            name = code.find(f'./{CAP_NS}valueName')
            value = code.find(f'./{CAP_NS}value')
            if name is not None and value is not None:
                geocodes[name.text] = value.text
                
        return {
            'id': alert_id,
            'title': entry.find(f'./{ATOM_NS}title').text,
            'summary': entry.find(f'./{ATOM_NS}summary').text,
            'event': cap_event.text if cap_event is not None else 'Unknown',
            'severity': cap_severity.text if cap_severity is not None else 'Unknown',
            'certainty': cap_certainty.text if cap_certainty is not None else 'Unknown',
            'urgency': cap_urgency.text if cap_urgency is not None else 'Unknown',
            'expires': cap_expires.text if cap_expires is not None else None,
            'geocode': geocodes
        }
    except Exception as e:
        logging.error(f"Failed to extract alert data: {e}")
        return None

async def process_new_alerts():
    """Process NWS alerts and post to Discord."""
    if not discord_channel_obj:
        logging.error("No Discord channel configured")
        return 0
    
    feed_content = await fetch_nws_feed()
    if not feed_content:
        return 0

    try:
        root = ET.fromstring(feed_content)
        entries = root.findall(f'./{ATOM_NS}entry')
        processed_count = 0

        for entry in entries[:MAX_PROCESS_PER_CYCLE]:
            try:
                alert_data = extract_alert_data(entry)
                if not alert_data:
                    continue

                # Check if already processed
                existing = get_posted_alert_info(alert_data['id'])
                if existing:
                    continue

                # Apply filters
                event_lower = alert_data['event'].lower()
                if (event_lower in current_blocked_event_types or
                    SEVERITY_LEVELS.get(alert_data['severity'], 0) < SEVERITY_LEVELS.get(current_min_severity, 0) or
                    CERTAINTY_LEVELS.get(alert_data['certainty'], 0) < CERTAINTY_LEVELS.get(current_min_certainty, 0) or
                    URGENCY_LEVELS.get(alert_data['urgency'], 0) < URGENCY_LEVELS.get(current_min_urgency, 0)):
                    logging.debug(f"Alert {alert_data['id']} filtered out")
                    continue

                # Create embed
                color = discord.Color.red() if alert_data['severity'] in ['Extreme', 'Severe'] else discord.Color.gold()
                embed = discord.Embed(
                    title=f"⚠️ {alert_data['title']}",
                    description=alert_data['summary'][:2000] if alert_data['summary'] else "No details available",
                    color=color
                )
                
                # Add fields
                embed.add_field(name="Event Type", value=alert_data['event'], inline=True)
                embed.add_field(name="Severity", value=alert_data['severity'], inline=True)
                embed.add_field(name="Urgency", value=alert_data['urgency'], inline=True)
                
                if alert_data['expires']:
                    try:
                        expires_ts = int(datetime.fromisoformat(alert_data['expires'].replace('Z', '+00:00')).timestamp())
                        embed.add_field(name="Expires", value=f"<t:{expires_ts}:R>", inline=True)
                    except Exception as e:
                        logging.warning(f"Failed to parse expiry time: {e}")
                
                # Post alert
                msg = await discord_channel_obj.send(embed=embed)
                record_alert_post(alert_data, msg.id)
                processed_count += 1
                logging.info(f"Posted alert {alert_data['id']}")
                await asyncio.sleep(POST_DELAY_SECONDS)
                
            except Exception as e:
                logging.error(f"Error processing single alert: {e}")
                continue

        return processed_count
    except Exception as e:
        error_id = await report_error(f"Error processing alerts: {e}", traceback_info=traceback.format_exc())
        logging.error(f"Failed to process alerts (ID: {error_id}): {e}")
        return 0

async def check_alerts():
    """Task to periodically check for new alerts."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            async with alert_processing_lock:
                count = await process_new_alerts()
                if count > 0:
                    logging.info(f"Posted {count} new alerts")
        except Exception as e:
            logging.error(f"Check alerts error: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

@bot.event 
async def on_ready():
    print(f'Discord bot logged in as {bot.user.name}')
    await setup_tasks()
    print('Tasks setup complete')

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("That command does not exist.  Please check your spelling and try again.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("You are missing a required argument.  Please check the help command for more information.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("You have provided a bad argument.  Please check the help command for more information.")
    elif isinstance(error, commands.TooManyArguments):
        await ctx.send("You have provided too many arguments.  Please check the help command for more information.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have the required permissions to use this command.")
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send("I do not have the required permissions to execute this command.")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("This command cannot be used in a private message.")
    elif isinstance(error, commands.PrivateMessageOnly):
        await ctx.send("This command can only be used in a private message.")
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("You do not have the required roles to use this command.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"This command is on cooldown.  Please try again in {error.retry_after:.2f} seconds.")
    elif isinstance(error, commands.DisabledCommand):
        await ctx.send("This command is disabled.")
    elif isinstance(error, commands.CommandInvokeError):
        await ctx.send(f"An error occurred while invoking this command.  Please try again later.  Error details: {error}")
    else:
        await ctx.send(f"An unexpected error occurred: {error}")

async def add_alert(location, event, message):
    try:
        await bot.db.execute("INSERT INTO alerts (location, event, message) VALUES ($1, $2, $3)", location, event, message)
        print(f"Alert added for {location} when {event} occurs.")
    except Exception as e:
        print(f"An error occurred while adding the alert: {e}")

async def get_alerts(location):
    try:
        alerts = await bot.db.fetch("SELECT event, message FROM alerts WHERE location = $1", location)
        return alerts
    except Exception as e:
        return []

async def remove_alert(location, event):
    try:
        await bot.db.execute("DELETE FROM alerts WHERE location = $1 AND event = $2", location, event)
        print(f"Alert removed for {location} when {event} occurs.")
    except Exception as e:
        print(f"An error occurred while removing the alert: {e}")

# Commands
@bot.command(name='add_alert', help='Add a new weather alert.')
async def add_alert_command(ctx, location, event, message):
    """Add a new weather alert."""
    await add_alert(location, event, message)
    await ctx.send(f"Alert added for {location} when {event} occurs.")

@bot.command(name='get_alerts', help='Get all weather alerts for a location.')
async def get_alerts_command(ctx, location):
    """Get all weather alerts for a location."""
    alerts = await get_alerts(location)
    if alerts:
        for alert in alerts:
            await ctx.send(f"When {alert['event']} occurs in {location}: {alert['message']}")
    else:
        await ctx.send(f"No alerts found for {location}.")

@bot.command(name='remove_alert', help='Remove a weather alert.')
async def remove_alert_command(ctx, location, event):
    """Remove a weather alert."""
    await remove_alert(location, event)
    await ctx.send(f"Alert removed for {location} when {event} occurs.")

async def get_nws_alerts() -> Optional[List]:
    """Fetch and parse NWS alerts from feed."""
    feed_content = await fetch_nws_feed()
    if not feed_content:
        return None
    try:
        root = ET.fromstring(feed_content)
        return root.findall(f'./{ATOM_NS}entry')
    except Exception as e:
        logging.error(f"Failed to parse NWS feed: {e}")
        return None

async def cleanup_database():
    """Clean up old alerts from database periodically."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            retention_date = (datetime.now(timezone.utc) - timedelta(days=DATABASE_RETENTION_DAYS))
            conn = None
            try:
                conn = sqlite3.connect(DATABASE_FILE)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM posted_alerts WHERE datetime(first_posted_utc) < datetime(?)",
                             (retention_date.isoformat(),))
                deleted = cursor.rowcount
                conn.commit()
                if deleted > 0:
                    logging.info(f"Cleaned up {deleted} old alerts")
            except sqlite3.Error as e:
                logging.error(f"Database cleanup error: {e}")
            finally:
                if conn:
                    conn.close()
        except Exception as e:
            logging.error(f"Cleanup task error: {e}")
        await asyncio.sleep(86400)  # Run once per day

async def change_status():
    """Rotate bot status message."""
    await bot.wait_until_ready()
    status_messages = [
        f"!help | v{SCRIPT_VERSION}",
        "!sub add <CODE>",
        "!wxalerts <CODE>",
        "National Weather Service"
    ]
    status_cycle = itertools.cycle(status_messages)
    while not bot.is_closed():
        try:
            status_text = next(status_cycle)
            await bot.change_presence(activity=discord.Activity(
                type=discord.ActivityType.listening,
                name=status_text
            ))
        except Exception as e:
            logging.error(f"Status rotation error: {e}")
        await asyncio.sleep(STATUS_ROTATION_MINUTES * 60)

bot.run(discord_token)