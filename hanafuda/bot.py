import asyncio
import json
import time
import requests
import logging
import argparse
from colorama import init, Fore, Style
from web3 import Web3
import aiohttp

init(autoreset=True)

RPC_URL = "https://mainnet.base.org"
CONTRACT_ADDRESS = "0xC5bf05cD32a14BFfb705Fb37a9d218895187376c"
API_URL = "https://hanafuda-backend-app-520478841386.us-central1.run.app/graphql"
CHAIN_ID = 8453
AMOUNT_ETH = 0.0000000001
API_KEY = "AIzaSyDipzN0VRfTPnMGhQ5PSzO27Cxm3DohJGY"

web3 = Web3(Web3.HTTPProvider(RPC_URL))
amount_wei = web3.to_wei(AMOUNT_ETH, 'ether')

with open("pvkey.txt", "r") as file:
    private_keys = [line.strip() for line in file if line.strip()]

with open("token.txt", "r") as file:
    refresh_tokens = [line.strip() for line in file if line.strip()]

contract_abi = '''
[
    {
        "constant": false,
        "inputs": [],
        "name": "depositETH",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    }
]
'''

contract = web3.eth.contract(address=CONTRACT_ADDRESS, abi=json.loads(contract_abi))

headers = {
    'Accept': '*/*',
    'Content-Type': 'application/json',
    'User-Agent': "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
}

def refresh_token_sync(refresh_token):
    url = f"https://securetoken.googleapis.com/v1/token?key={API_KEY}"
    response = requests.post(url, headers={"Content-Type": "application/json"},
                             data=json.dumps({
                                 "grant_type": "refresh_token",
                                 "refresh_token": refresh_token,
                             }))
    if response.status_code != 200:
        raise Exception("Failed to refresh access token")
    return response.json()

def sync_transaction(tx_hash, access_token):
    headers_graphql = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {access_token}"
    }
    query = """
        mutation SyncEthereumTx($chainId: Int!, $txHash: String!) {
            syncEthereumTx(chainId: $chainId, txHash: $txHash)
        }
    """
    variables = {"chainId": CHAIN_ID, "txHash": tx_hash}
    response = requests.post(API_URL, json={"query": query, "variables": variables}, headers=headers_graphql)
    if response.status_code != 200:
        raise Exception(f"Gagal sync tx: {response.text}")
    return response.json()

async def colay(session, url, method, payload_data=None):
    async with session.request(method, url, headers=headers, json=payload_data) as response:
        if response.status != 200:
            raise Exception(f'HTTP error! Status: {response.status}')
        return await response.json()

async def refresh_token_async(session, refresh_token):
    async with session.post(
        f'https://securetoken.googleapis.com/v1/token?key={API_KEY}',
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=f'grant_type=refresh_token&refresh_token={refresh_token}'
    ) as response:
        if response.status != 200:
            raise Exception("Failed to refresh access token")
        return await response.json()

async def handle_grow_and_garden(session, refresh_token):
    new_token_data = await refresh_token_async(session, refresh_token)
    new_access_token = new_token_data.get('access_token')
    headers['authorization'] = f'Bearer {new_access_token}'

    info_query = {
        "query": """
            query getCurrentUser {
                currentUser { id totalPoint depositCount }
                getGardenForCurrentUser {
                    gardenStatus { growActionCount gardenRewardActionCount }
                }
            }
        """,
        "operationName": "getCurrentUser"
    }

    info = await colay(session, API_URL, 'POST', info_query)
    balance = info['data']['currentUser']['totalPoint']
    deposit = info['data']['currentUser']['depositCount']
    grow = info['data']['getGardenForCurrentUser']['gardenStatus']['growActionCount']
    garden = info['data']['getGardenForCurrentUser']['gardenStatus']['gardenRewardActionCount']

    print(f"{Fore.GREEN}POINTS: {balance} | Deposit: {deposit} | Grow left: {grow} | Garden left: {garden}")

    if grow > 0:
        grow_query = {
            "query": """
                mutation executeGrowAction {
                    executeGrowAction(withAll: true) {
                        totalValue
                        multiplyRate
                    }
                    executeSnsShare(actionType: GROW, snsType: X) {
                        bonus
                    }
                }
            """,
            "operationName": "executeGrowAction"
        }

        try:
            result = await colay(session, API_URL, 'POST', grow_query)
            reward = result['data']['executeGrowAction']['totalValue']
            print(f"{Fore.GREEN}Reward: {reward} | New Balance: {balance + reward}")
        except Exception as e:
            print(f"{Fore.RED}Grow Error: {str(e)}")

    while garden >= 10:
        garden_query = {
            "query": """
                mutation executeGardenRewardAction($limit: Int!) {
                    executeGardenRewardAction(limit: $limit) {
                        data { cardId group }
                        isNew
                    }
                }
            """,
            "variables": {"limit": 10},
            "operationName": "executeGardenRewardAction"
        }
        garden_res = await colay(session, API_URL, 'POST', garden_query)
        card_ids = [item['data']['cardId'] for item in garden_res['data']['executeGardenRewardAction']]
        print(f"{Fore.CYAN}Garden Opened: {card_ids}")
        garden -= 10

def run_deposit(num_tx):
    nonces = {key: web3.eth.get_transaction_count(web3.eth.account.from_key(key).address) for key in private_keys}

    for i in range(num_tx):
        for pk, refresh_token in zip(private_keys, refresh_tokens):
            from_address = web3.eth.account.from_key(pk).address
            short_addr = from_address[:4] + "..." + from_address[-4:]

            try:
                tokens = refresh_token_sync(refresh_token)
                access_token = tokens["access_token"]

                tx = contract.functions.depositETH().build_transaction({
                    'from': from_address,
                    'value': amount_wei,
                    'gas': 50000,
                    'gasPrice': web3.eth.gas_price,
                    'nonce': nonces[pk],
                })

                signed_tx = web3.eth.account.sign_transaction(tx, pk)
                tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
                tx_hex = tx_hash.hex()

                print(f"{Fore.YELLOW}[{short_addr}] TX Hash: {tx_hex}")
                time.sleep(3)
                sync_result = sync_transaction(tx_hex, access_token)
                print(f"{Fore.GREEN}Synced! Result: {sync_result}")

                nonces[pk] += 1
                # time.sleep(5)
            except Exception as e:
                print(f"{Fore.RED}Deposit Error: {str(e)}")

async def main(mode, num_transactions=None):
    if mode == '1':
        if not num_transactions:
            num_transactions = int(input(Fore.YELLOW + "Enter transaction count: "))
        run_deposit(num_transactions)
    elif mode == '2':
        async with aiohttp.ClientSession() as session:
            while True:
                for token in refresh_tokens:
                    await handle_grow_and_garden(session, token)
                print(f"{Fore.MAGENTA}Cooldown 10 minutes...")
                time.sleep(600)
    else:
        print(Fore.RED + "Invalid mode.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Hanafuda All-in-One Bot")
    parser.add_argument('-a', '--action', choices=['1', '2'], help='1: Deposit ETH | 2: Grow & Garden')
    parser.add_argument('-tx', '--transactions', type=int, help='Transaction count (for action 1)')
    args = parser.parse_args()

    if not args.action:
        args.action = input("Choose mode (1=Deposit, 2=Grow): ").strip()

    asyncio.run(main(args.action, args.transactions))
