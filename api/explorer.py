import itertools
import datetime
import json
import connexion.problem
from services.tusc_websocket_client import client as tusc_ws_client
from services.tusc_elasticsearch_client import client as tusc_es_client
from services.cache import cache
from . import es_wrapper
import config
import logging


def _bad_request(detail):
    return connexion.problem(400, 'Bad Request', detail)


def _get_core_asset_name():
    if config.TESTNET == 1:
        return config.CORE_ASSET_SYMBOL_TESTNET
    else:
        return config.CORE_ASSET_SYMBOL


def get_header():
    response = tusc_ws_client.request(
        'database', 'get_dynamic_global_properties', [])
    return _add_global_informations(response, tusc_ws_client)


@cache.memoize()
def get_account(account_id):
    return tusc_ws_client.request('database', 'get_accounts', [[account_id]])[0]


def get_account_name(account_id):
    account = get_account(account_id)
    return account['name']


@cache.memoize()
def _get_account_id(account_name):
    if not _is_object(account_name):
        account = tusc_ws_client.request(
            'database', 'lookup_account_names', [[account_name], 0])
        return account[0]['id']
    else:
        return account_name


def _add_global_informations(response, ws_client):
    # get market cap
    core_asset = ws_client.get_object('2.3.0')
    current_supply = core_asset["current_supply"]
    confidential_supply = core_asset["confidential_supply"]
    market_cap = int(current_supply) + int(confidential_supply)
    # TODO: add market cap based on correct maximum.
    #response["bts_market_cap"] = int(market_cap/100000000)

    global_properties = ws_client.get_global_properties()
    response["committee_count"] = len(
        global_properties["active_committee_members"])
    response["witness_count"] = len(global_properties["active_witnesses"])

    return response


def _enrich_operation(operation, ws_client):
    dynamic_global_properties = ws_client.request(
        'database', 'get_dynamic_global_properties', [])
    operation["accounts_registered_this_interval"] = dynamic_global_properties["accounts_registered_this_interval"]

    return _add_global_informations(operation, ws_client)


def get_operation(operation_id):
    res = es_wrapper.get_single_operation(operation_id)
    operation = {
        "op": res["operation_history"]["op_object"],
        "op_type": res["operation_type"],
        "block_num": res["block_data"]["block_num"],
        "op_in_trx": res["operation_history"]["op_in_trx"],
        "result": json.loads(res["operation_history"]["operation_result"]),
        "trx_in_block": res["operation_history"]["trx_in_block"],
        "virtual_op": res["operation_history"]["virtual_op"],
        "block_time": res["block_data"]["block_time"],
        "trx_id": res["block_data"]["trx_id"]
    }

    operation = _enrich_operation(operation, tusc_ws_client)
    return operation


def get_accounts(start=0, limit=100):
    core_asset_holders = get_asset_holders('1.3.0', start=start, limit=limit)
    return core_asset_holders


def get_full_account(account_id):
    account = tusc_ws_client.request(
        'database', 'get_full_accounts', [[account_id], 0])[0][1]
    return account


@cache.memoize()
def get_assets():
    results = []

    # Get all assets active the last 24h.
    markets = tusc_es_client.get_markets(
        'now-1d', 'now', quote=config.CORE_ASSET_ID)
    tusc_volume = 0.0  # BTS volume is the sum of all the others.
    for asset_id in itertools.chain(markets.keys(), [config.CORE_ASSET_ID]):
        asset = get_asset_and_volume(asset_id)
        holders_count = get_asset_holders_count(asset_id)
        tusc_volume += float(asset['volume'])
        results.append({
            'asset_name': asset['symbol'],  # asset name
            'asset_id': asset_id,  # asset id
            'latest_price': asset['latest_price'],  # price in bts
            # 24h volume
            '24h_volume': float(asset['volume']) if asset_id != config.CORE_ASSET_ID else tusc_volume,
            # float(markets[asset_id][config.CORE_ASSET_ID]['volume']), # 24h volume (from ES) / should be divided by core asset precision
            'market_cap': asset['mcap'],  # market cap
            # type: Core Asset / Smart Asset / User Issued Asset
            'asset_type': _get_asset_type(asset),
            'current_supply': int(asset['current_supply']),  # Supply
            'holders_count': holders_count,  # Number of holders
            'precision': asset['precision']  # Asset precision
        })

    results.sort(key=lambda a: -a['24h_volume'])  # sort by volume
    return results


def get_fees():
    return tusc_ws_client.get_global_properties()


@cache.memoize()
def _get_asset_id_and_precision(asset_name):
    asset = tusc_ws_client.request(
        'database', 'lookup_asset_symbols', [[asset_name], 0])[0]
    return (asset["id"], 10 ** asset["precision"])


@cache.memoize()
def get_asset(asset_id):
    asset = None
    if not _is_object(asset_id):
        asset = tusc_ws_client.request(
            'database', 'lookup_asset_symbols', [[asset_id], 0])[0]
    else:
        asset = tusc_ws_client.request(
            'database', 'get_assets', [[asset_id], 0])[0]

    dynamic_asset_data = tusc_ws_client.get_object(
        asset["dynamic_asset_data_id"])
    asset["current_supply"] = dynamic_asset_data["current_supply"]
    asset["confidential_supply"] = dynamic_asset_data["confidential_supply"]
    asset["accumulated_fees"] = dynamic_asset_data["accumulated_fees"]
    asset["fee_pool"] = dynamic_asset_data["fee_pool"]

    issuer = tusc_ws_client.get_object(asset["issuer"])
    asset["issuer_name"] = issuer["name"]

    return asset


@cache.memoize()
def get_asset_and_volume(asset_id):
    asset = get_asset(asset_id)

    core_symbol = _get_core_asset_name()

    if asset['symbol'] != core_symbol:
        volume = _get_volume(core_symbol, asset['symbol'])
        asset['volume'] = volume['base_volume']

        ticker = get_ticker(core_symbol, asset['symbol'])
        latest_price = float(ticker['latest'])
        asset['latest_price'] = latest_price

        asset['mcap'] = int(asset['current_supply']) * latest_price
    else:
        asset['volume'] = 0
        asset['mcap'] = int(asset['current_supply'])
        asset['latest_price'] = 1

    return asset


def get_block(block_num):
    block = tusc_ws_client.request('database', 'get_block', [block_num, 0])
    return block


def get_ticker(base, quote):
    return tusc_ws_client.request('database', 'get_ticker', [base, quote])


def _get_volume(base, quote):
    return tusc_ws_client.request('database', 'get_24_volume', [base, quote])


def get_object(object):
    return tusc_ws_client.get_object(object)


def _ensure_asset_id(asset_id):
    if not _is_object(asset_id):
        id, _ = _get_asset_id_and_precision(asset_id)
        return id
    else:
        return asset_id


def get_asset_holders_count(asset_id):
    asset_id = _ensure_asset_id(asset_id)
    return tusc_ws_client.request('asset', 'get_asset_holders_count', [asset_id])


def get_asset_holders(asset_id, start=0, limit=20):
    asset_id = _ensure_asset_id(asset_id)
    asset_holders = tusc_ws_client.request(
        'asset', 'get_asset_holders', [asset_id, start, limit])
    return asset_holders

# Added by rabTAI


def get_total_supply(object):
    maxSupply = tusc_ws_client.get_object(object)
    return maxSupply['current_max_supply']


def get_workers():
    workers_count = tusc_ws_client.request('database', 'get_worker_count', [])
    workers = tusc_ws_client.request('database', 'get_objects', [
                                     ['1.11.{}'.format(i) for i in range(0, workers_count)]])

    result = []
    for worker in workers:
        if worker:
            worker["worker_account_name"] = get_account_name(
                worker["worker_account"])
            result.append([worker])

    result = result[::-1]  # Reverse list.
    return result


def _is_object(string):
    return len(string.split(".")) == 3


@cache.memoize()
def _get_markets(asset_id):
    markets = tusc_es_client.get_markets('now-1d', 'now', quote=asset_id)

    results = []
    for (base_id, quotes) in markets.items():
        base_asset = get_asset(base_id)
        for (quote_id, data) in quotes.items():
            quote_asset = get_asset(quote_id)
            ticker = get_ticker(base_id, quote_id)
            latest_price = float(ticker['latest'])
            results.append({
                'pair': '{}/{}'.format(quote_asset['symbol'], base_asset['symbol']),
                'latest_price': latest_price,
                '24h_volume': data['volume'] / 10**quote_asset['precision'],
                'quote_id': quote_id,
                'base_id': base_id
            })

    return results


def get_markets(asset_id):
    asset_id = _ensure_asset_id(asset_id)
    return _get_markets(asset_id)


@cache.memoize()
def get_most_active_markets():
    markets = tusc_es_client.get_markets('now-1d', 'now')

    flatten_markets = []
    for (base, quotes) in markets.items():
        for (quote, data) in quotes.items():
            flatten_markets.append({
                'base': base,
                'quote': quote,
                'volume': data['volume'],
                'nb_operations': data['nb_operations']
            })
    flatten_markets.sort(key=lambda m: -m['nb_operations'])

    top_markets = flatten_markets[:100]

    results = []
    for m in top_markets:
        base_asset = get_asset(m['base'])
        quote_asset = get_asset(m['quote'])
        ticker = get_ticker(m['base'], m['quote'])
        latest_price = float(ticker['latest'])
        results.append({
            'pair':  '{}/{}'.format(quote_asset['symbol'], base_asset['symbol']),
            'latest_price': latest_price,
            '24h_volume': m['volume'] / 10**quote_asset['precision'],
            'quote_id': m['quote'],
            'base_id': m['base']
        })

    return results


def _ensure_safe_limit(limit):
    if not limit:
        limit = 10
    elif int(limit) > 50:
        limit = 50
    return limit


def get_order_book(base, quote, limit=False):
    limit = _ensure_safe_limit(limit)
    order_book = tusc_ws_client.request(
        'database', 'get_order_book', [base, quote, limit])
    return order_book


def get_margin_positions(account_id):
    margin_positions = tusc_ws_client.request(
        'database', 'get_margin_positions', [account_id])
    return margin_positions


def get_witnesses():
    witnesses_count = tusc_ws_client.request(
        'database', 'get_witness_count', [])
    witnesses = tusc_ws_client.request('database', 'get_objects', [
                                       ['1.5.{}'.format(w) for w in range(0, witnesses_count)]])
    result = []
    for witness in witnesses:
        if witness:
            witness["witness_account_name"] = get_account_name(
                witness["witness_account"])
            result.append(witness)

    result = sorted(result, key=lambda k: int(k['total_votes']))
    result = result[::-1]  # Reverse list.
    return result


def get_committee_members():
    committee_count = tusc_ws_client.request(
        'database', 'get_committee_count', [])
    committee_members = tusc_ws_client.request('database', 'get_objects', [
                                               ['1.4.{}'.format(i) for i in range(0, committee_count)]])

    result = []
    for committee_member in committee_members:
        if committee_member:
            committee_member["committee_member_account_name"] = get_account_name(
                committee_member["committee_member_account"])
            result.append([committee_member])

    result = sorted(result, key=lambda k: int(k[0]['total_votes']))
    result = result[::-1]  # this reverses array

    return result


def get_top_proxies():
    holders = _get_holders()

    total_votes = 0
    for key in holders:
        total_votes = total_votes + int(holders[key]['balance'])

    proxies = []
    for key in holders:
        holder = holders[key]
        if 'follower_count' in holder:
            proxy_amount = int(holder['balance']) + \
                int(holder['follower_amount'])
            proxy_total_percentage = float(
                int(proxy_amount) * 100.0 / int(total_votes))
            proxies.append({
                'id': holder['owner']['id'],
                'name': holder['owner']['name'],
                'tusc_weight': proxy_amount,
                'followers': holder['follower_count'],
                'tusc_weight_percentage': proxy_total_percentage
            })

    # Reverse amount order
    proxies = sorted(proxies, key=lambda k: -k['tusc_weight'])

    return proxies


def _get_accounts_by_chunks_via_es(account_ids, chunk_size=1000):
    all_accounts = []
    for i in range(0, len(account_ids), chunk_size):
        accounts = tusc_es_client.get_accounts(
            account_ids[i:i + chunk_size], size=chunk_size)
        all_accounts.extend(accounts)
    return all_accounts


def _get_accounts_by_chunks_via_ws(account_ids, chunk_size=1000):
    all_accounts = []
    for i in range(0, len(account_ids), chunk_size):
        accounts = tusc_ws_client.request('database', 'get_accounts', [
                                          account_ids[i:i + chunk_size]])
        all_accounts.extend(accounts)
    return all_accounts

# FIXME: Should not be needed anymore when https://github.com/bitshares/bitshares-core/issues/1652 will be resolved.


def _load_missing_accounts_via_ws(account_ids, accounts_already_loaded):
    accounts_ids_already_loaded = [account['id']
                                   for account in accounts_already_loaded]
    accounts_ids_to_load = list(
        set(account_ids) - set(accounts_ids_already_loaded))
    logging.info("{} accounts to load via websocket".format(
        len(accounts_ids_to_load)))
    missing_accounts = _get_accounts_by_chunks_via_ws(accounts_ids_to_load)
    return accounts_already_loaded + missing_accounts


def _get_voting_account(holder):
    if 'options' in holder['owner'] and 'voting_account' in holder['owner']['options']:
        return holder['owner']['options']['voting_account']
    else:
        return None


@cache.memoize()
def _get_holders():
    balances = tusc_es_client.get_balances(asset_id=config.CORE_ASSET_ID)
    account_ids = [balance['owner'] for balance in balances]
    accounts = _get_accounts_by_chunks_via_es(account_ids)
    accounts = _load_missing_accounts_via_ws(account_ids, accounts)
    holders_by_account_id = {}
    for balance in balances:
        holders_by_account_id[balance['owner']] = balance
    for account in accounts:
        holders_by_account_id[account['id']]['owner'] = account
    for holder in holders_by_account_id.values():
        if 'options' in holder['owner'] and 'voting_account' in holder['owner']['options']:
            proxy_id = holder['owner']['options']['voting_account']
            if proxy_id != '1.2.5':
                if proxy_id not in holders_by_account_id:
                    proxy_without_balance = {
                        'owner': get_account(proxy_id),
                        'balance': 0,
                        'asset_type': config.CORE_ASSET_ID
                    }
                    holders_by_account_id[proxy_id] = proxy_without_balance
                proxy = holders_by_account_id[proxy_id]
                if 'follower_amount' not in proxy:
                    proxy['follower_amount'] = 0
                    proxy['follower_count'] = 0
                proxy['follower_amount'] += int(holder['balance'])
                proxy['follower_count'] += 1

    return holders_by_account_id


def get_top_holders():
    holders = _get_holders()
    # FIXME: Why without delegation???
    holders_without_vote_delegation = []
    for key in holders:
        if _get_voting_account(holders[key]) == '1.2.5':
            holders_without_vote_delegation.append(holders[key])

    holders_without_vote_delegation.sort(key=lambda h: -int(h['balance']))
    top_holders = []
    for holder in holders_without_vote_delegation[:10]:
        top_holders.append({
            'account_id': holder['owner']['id'],
            'account_name': holder['owner']['name'],
            'amount': int(holder['balance']),
            'voting_account': _get_voting_account(holder)
        })
    return top_holders


def _get_formatted_proxy_votes(proxies, vote_id):
    return list(map(lambda p: '{}:{}'.format(p['id'], 'Y' if vote_id in p["options"]["votes"] else '-'), proxies))


def get_witnesses_votes():
    proxies = get_top_proxies()
    proxies = proxies[:10]
    proxies = tusc_ws_client.request('database', 'get_objects', [
                                     [p['id'] for p in proxies]])

    witnesses = get_witnesses()
    witnesses = witnesses[:25]  # FIXME: Witness number is variable.

    witnesses_votes = []
    for witness in witnesses:
        vote_id = witness["vote_id"]
        id_witness = witness["id"]
        witness_account_name = witness["witness_account_name"]
        proxy_votes = _get_formatted_proxy_votes(proxies, vote_id)

        witnesses_votes.append({
            'witness_account_name': witness_account_name,
            'witness_id': id_witness,
            'top_proxy_votes': proxy_votes
        })

    return witnesses_votes


def get_workers_votes():
    proxies = get_top_proxies()
    proxies = proxies[:10]
    proxies = tusc_ws_client.request('database', 'get_objects', [
                                     [p['id'] for p in proxies]])

    workers = get_workers()
    workers = workers[:30]

    workers_votes = []
    for worker in workers:
        vote_id = worker[0]["vote_for"]
        id_worker = worker[0]["id"]
        worker_account_name = worker[0]["worker_account_name"]
        worker_name = worker[0]["name"]
        proxy_votes = _get_formatted_proxy_votes(proxies, vote_id)

        workers_votes.append({
            'worker_account_name': worker_account_name,
            'worker_id': id_worker,
            'worker_name': worker_name,
            'top_proxy_votes': proxy_votes
        })

    return workers_votes


def get_committee_votes():
    proxies = get_top_proxies()
    proxies = proxies[:10]
    proxies = tusc_ws_client.request('database', 'get_objects', [
                                     [p['id'] for p in proxies]])

    committee_members = get_committee_members()
    committee_members = committee_members[:11]

    committee_votes = []
    for committee_member in committee_members:
        vote_id = committee_member[0]["vote_id"]
        id_committee = committee_member[0]["id"]
        committee_account_name = committee_member[0]["committee_member_account_name"]
        proxy_votes = _get_formatted_proxy_votes(proxies, vote_id)

        committee_votes.append({
            'committee_account_name': committee_account_name,
            'committee_id': id_committee,
            'top_proxy_votes': proxy_votes
        })

    return committee_votes


def get_top_markets():
    markets = get_most_active_markets()
    markets.sort(key=lambda a: -a['24h_volume'])  # sort by volume
    top = markets[:7]
    return top


def get_top_smartcoins():
    smartcoins = [a for a in get_assets() if a['asset_type'] == 'SmartCoin']
    return smartcoins[:7]


@cache.memoize()
def get_top_uias():
    uias = [a for a in get_assets() if a['asset_type'] == 'User Issued']
    return uias[:7]


def lookup_accounts(start):
    accounts = tusc_ws_client.request(
        'database', 'lookup_accounts', [start, 1000])
    return accounts


def lookup_assets(start):
    asset_names = tusc_es_client.get_asset_names(start)
    return [[asset_name] for asset_name in asset_names]


def get_last_block_number():
    dynamic_global_properties = tusc_ws_client.request(
        'database', 'get_dynamic_global_properties', [])
    return dynamic_global_properties["head_block_number"]


def get_last_block_time():
    dynamic_global_properties = tusc_ws_client.request(
        'database', 'get_dynamic_global_properties', [])
    return dynamic_global_properties["time"]


def get_account_history(account_id, page, search_after):
    account_id = _get_account_id(account_id)

    from_ = page * 20
    operations = es_wrapper.get_account_history(
        account_id=account_id, from_=from_, search_after=search_after, size=20, sort_by='-account_history.operation_id.keyword')

    results = []
    for op in operations:
        results.append({
            "op": op["operation_history"]["op_object"],
            "op_type": op["operation_type"],
            "block_num": op["block_data"]["block_num"],
            "id": op["account_history"]["operation_id"],
            "op_in_trx": op["operation_history"]["op_in_trx"],
            "result": json.loads(op["operation_history"]["operation_result"]),
            "timestamp": op["block_data"]["block_time"],
            "trx_in_block": op["operation_history"]["trx_in_block"],
            "virtual_op": op["operation_history"]["virtual_op"]
        })

    return results


def get_fill_order_history(base, quote):
    fill_order_history = tusc_ws_client.request(
        'history', 'get_fill_order_history', [base, quote, 100])
    return fill_order_history


def get_dex_total_volume():
    volume = 0.0
    market_cap = 0.0
    for a in get_assets():
        if a['asset_id'] != config.CORE_ASSET_ID:
            volume += a['24h_volume']
        market_cap += a['market_cap']

    res = {
        "volume_tusc": round(volume),
        "market_cap_tusc": round(market_cap),
    }

    return res


def get_daily_volume_dex_dates():
    base = datetime.date.today()
    date_list = [base - datetime.timedelta(days=x) for x in range(0, 60)]
    date_list = [d.strftime("%Y-%m-%d") for d in date_list]
    return list(reversed(date_list))


@cache.memoize(86400)  # 1d TTL
def get_daily_volume_dex_data():
    daily_volumes = tusc_es_client.get_daily_volume('now-60d', 'now')
    core_asset_precision = 10 ** get_asset(config.CORE_ASSET_ID)['precision']

    results = [int(daily_volume['volume'] / core_asset_precision)
               for daily_volume in daily_volumes]
    return results


def get_all_asset_holders(asset_id):
    asset_id = _ensure_asset_id(asset_id)

    all = []

    asset_holders = get_asset_holders(asset_id, start=0, limit=100)
    all.extend(asset_holders)

    len_result = len(asset_holders)
    start = 100
    while len_result == 100:
        start = start + 100
        asset_holders = get_asset_holders(asset_id, start=start, limit=100)
        len_result = len(asset_holders)
        all.extend(asset_holders)

    return all


def get_referrer_count(account_id):
    account_id = _get_account_id(account_id)

    count, _ = tusc_es_client.get_accounts_with_referrer(account_id, size=0)

    return count


def get_all_referrers(account_id, page=0):
    account_id = _get_account_id(account_id)

    page_size = 20
    offset = int(page) * page_size
    _, accounts = tusc_es_client.get_accounts_with_referrer(
        account_id, size=page_size, from_=offset)

    results = []
    for account in accounts:
        results.append({
            'account_id': account['id'],
            'account_name': account['name'],
            'referrer': account['referrer'],
            # % of reward that goes to referrer
            'referrer_rewards_percentage': account['referrer_rewards_percentage'],
            'lifetime_referrer': account['lifetime_referrer'],
            # % of reward that goes to lifetime referrer
            'lifetime_referrer_fee_percentage': account['lifetime_referrer_fee_percentage']
        })

    return results


def get_grouped_limit_orders(quote, base, group=10, limit=False):
    limit = _ensure_safe_limit(limit)

    base = _ensure_asset_id(base)
    quote = _ensure_asset_id(quote)

    grouped_limit_orders = tusc_ws_client.request(
        'orders', 'get_grouped_limit_orders', [base, quote, group, None, limit])

    return grouped_limit_orders


def _get_asset_type(asset):
    if asset['id'] == config.CORE_ASSET_ID:
        return 'Core Token'
    elif asset['issuer'] == '1.2.0':
        return 'SmartCoin'
    else:
        return 'User Issued'


OPERATION_TYPES = [
    {'id': 0, 'name': 'transfer', 'virtual': False},
    {'id': 2, 'name': 'account_create', 'virtual': False},
    {'id': 3, 'name': 'account_update', 'virtual': False},
    {'id': 4, 'name': 'account_whitelist', 'virtual': False},
    {'id': 5, 'name': 'account_upgrade', 'virtual': False},
    {'id': 6, 'name': 'account_transfer', 'virtual': False},
    {'id': 7, 'name': 'asset_update', 'virtual': False},
    {'id': 8, 'name': 'asset_reserve', 'virtual': False},
    {'id': 9, 'name': 'witness_create', 'virtual': False},
    {'id': 10, 'name': 'witness_update', 'virtual': False},
    {'id': 11, 'name': 'proposal_create', 'virtual': False},
    {'id': 12, 'name': 'proposal_update', 'virtual': False},
    {'id': 13, 'name': 'proposal_delete', 'virtual': False},
    {'id': 14, 'name': 'withdraw_permission_create', 'virtual': False},
    {'id': 15, 'name': 'withdraw_permission_update', 'virtual': False},
    {'id': 16, 'name': 'withdraw_permission_claim', 'virtual': False},
    {'id': 17, 'name': 'withdraw_permission_delete', 'virtual': False},
    {'id': 18, 'name': 'committee_member_create', 'virtual': False},
    {'id': 19, 'name': 'committee_member_update', 'virtual': False},
    {'id': 20, 'name': 'committee_member_update_global_parameters', 'virtual': False},
    {'id': 21, 'name': 'vesting_balance_create', 'virtual': False},
    {'id': 22, 'name': 'vesting_balance_withdraw', 'virtual': False},
    {'id': 23, 'name': 'worker_create', 'virtual': False},
    {'id': 24, 'name': 'custom', 'virtual': False},
    {'id': 25, 'name': 'assert', 'virtual': False},
    {'id': 26, 'name': 'balance_claim', 'virtual': False},
    {'id': 27, 'name': 'override_transfer', 'virtual': False},
    {'id': 28, 'name': 'transfer_to_blind', 'virtual': False},
    {'id': 29, 'name': 'blind_transfer', 'virtual': False},
    {'id': 30, 'name': 'transfer_from_blind', 'virtual': False},
    {'id': 31, 'name': 'htlc_create', 'virtual': False},
    {'id': 32, 'name': 'htlc_redeem', 'virtual': False},
    {'id': 33, 'name': 'htlc_redeemed', 'virtual': True},
    {'id': 34, 'name': 'htlc_extend', 'virtual': False},
    {'id': 35, 'name': 'htlc_refund', 'virtual': True},
    {'id': 36, 'name': 'sale', 'virtual': False}

]


def get_operation_type(id=None, name=None):
    if id != None:
        if name != None:
            return _bad_request("Invalid parameters, either 'id' or 'name' should be provided")
        if id < 0 or id > len(OPERATION_TYPES):
            return _bad_request("Invalid parameter 'id', it should be in range 0..{}".format(len(OPERATION_TYPES) - 1))
        return OPERATION_TYPES[id]

    if name != None and name != '':
        operation_type = filter(
            lambda operation_type: operation_type['name'] == name, OPERATION_TYPES)
        if len(operation_type) == 0:
            return _bad_request("Invalid parameter 'name', unknown operation type '{}'".format(name))
        return operation_type[0]

    return _bad_request("Invalid parameters, either 'id' or 'name' should be provided")


def get_operation_types():
    return OPERATION_TYPES
