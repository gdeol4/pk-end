#!/usr/bin/env python3
"""
PolyKye Off‑Chain Processor — ultra‑lean gas version
• Listens for new targets
• Pins stub data to IPFS (Pinata)
• Calls submitResult with minimal gas / fee
"""

import json, time, random, requests
from pathlib import Path
from web3 import Web3

# ─── RPC / Contract / Wallet ────────────────────────────────────
RPC_URL       = "https://ethereum-sepolia.publicnode.com"
CONTRACT_ADDR = "0xBc43a97906e2061De0B92CaFC78e1912CE558012"

OWNER_ADDR = "0xA9060179b16Cfddc66002B3B68714A84739EA371"
OWNER_KEY  = "e326b930fa1669cb142f9822c8b25dbfb3ff9d59d8cb360f7e17566ff5b70f35"

# ─── Pinata (free tier) ─────────────────────────────────────────
PINATA_JWT  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySW5mb3JtYXRpb24iOnsiaWQiOiI1ZDQ0NDVhOC00MGYxLTQ5ZTctOGJlYi0zNTQ3MzQ5YmNhZGQiLCJlbWFpbCI6Imd1cmthbWFsLmRldkBnbWFpbC5jb20iLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwicGluX3BvbGljeSI6eyJyZWdpb25zIjpbeyJkZXNpcmVkUmVwbGljYXRpb25Db3VudCI6MSwiaWQiOiJGUkExIn0seyJkZXNpcmVkUmVwbGljYXRpb25Db3VudCI6MSwiaWQiOiJOWUMxIn1dLCJ2ZXJzaW9uIjoxfSwibWZhX2VuYWJsZWQiOmZhbHNlLCJzdGF0dXMiOiJBQ1RJVkUifSwiYXV0aGVudGljYXRpb25UeXBlIjoic2NvcGVkS2V5Iiwic2NvcGVkS2V5S2V5IjoiZThkZTU2OWY4YTE1N2VmNmI0OGEiLCJzY29wZWRLZXlTZWNyZXQiOiIzZGI2ZmVhZjRiODhiZGJmMWE3NjM2NWQ3ZDQ5ZmJiNmEyYWI1ZTNmOTM1NWY1NmNlMzBkOGE2OTE2ZTg4Yjk0IiwiZXhwIjoxNzc4ODEzMjA5fQ.RlFiUzwO9aF03Ky_s7URqZ76P_8iW4iyDn4JY-P0LFE"        # full JWT here
PINATA_BASE = "https://api.pinata.cloud"

# ─── Connect RPC ───────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 30}))
assert w3.is_connected(), "Sepolia RPC unreachable"
chain_id = w3.eth.chain_id
print(f"✓ connected to Sepolia chain {chain_id}")

# ─── Minimal ABI ───────────────────────────────────────────────
ABI = [
    {   # event TargetSubmitted(address user,uint256 targetId,string target)
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "internalType": "address", "name": "user",     "type": "address"},
            {"indexed": True,  "internalType": "uint256", "name": "targetId", "type": "uint256"},
            {"indexed": False, "internalType": "string",  "name": "target",   "type": "string"}],
        "name": "TargetSubmitted", "type": "event"
    },
    {   # function submitResult(uint256,string,string)
        "inputs": [
            {"internalType": "uint256", "name": "targetId", "type": "uint256"},
            {"internalType": "string",  "name": "smiles",   "type": "string"},
            {"internalType": "string",  "name": "ipfsHash", "type": "string"}],
        "name": "submitResult", "outputs": [], "stateMutability": "nonpayable", "type": "function"
    },
    {   # view helpers
        "inputs": [], "name": "targetCount",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view", "type": "function"
    },
    {
        "inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "name": "targets",
        "outputs": [
            {"internalType": "address", "name": "user",      "type": "address"},
            {"internalType": "string",  "name": "target",    "type": "string"},
            {"internalType": "uint256", "name": "timestamp", "type": "uint256"},
            {"internalType": "bool",    "name": "processed", "type": "bool"}],
        "stateMutability": "view", "type": "function"
    }
]

contract = w3.eth.contract(address=CONTRACT_ADDR, abi=ABI)

# ─── Load stub optimisation data ───────────────────────────────
stubs = json.loads(Path("molecular_data.json").read_text())["molecular_optimizations"]
by_target = {}
for entry in stubs:
    by_target.setdefault(entry["original"]["target"], []).append(entry)
print(f"Loaded stub data for {len(by_target)} target(s).")

# ─── Pin JSON to IPFS ───────────────────────────────────────────
def pin_json(payload: dict) -> str:
    r = requests.post(
        f"{PINATA_BASE}/pinning/pinJSONToIPFS",
        headers={"Authorization": f"Bearer {PINATA_JWT}", "Content-Type": "application/json"},
        json=payload, timeout=30)
    r.raise_for_status()
    return r.json()["IpfsHash"]

# ─── Main polling loop ─────────────────────────────────────────
last_seen = -1
while True:
    try:
        total = contract.functions.targetCount().call()
    except Exception as e:
        print("RPC error:", e); time.sleep(5); continue

    for tid in range(last_seen + 1, total):
        user, target, ts, done = contract.functions.targets(tid).call()
        print(f"\n► targetId {tid} processed={done} target='{target}'")
        last_seen = tid
        if done:
            continue

        stub = random.choice(by_target.get(target, [])) if target in by_target else None
        if not stub:
            print("   ⚠ no stub data – skipped"); continue

        smiles = stub["optimized"]["smiles"]

        # 1. Pin to IPFS
        try:
            cid = pin_json({
                "target":    target,
                "original":  stub["original"],
                "optimized": stub["optimized"],
                "rationale": stub["rationale"]
            })
            print("   ✓ IPFS CID:", cid)
        except Exception as e:
            print("   ✖ IPFS pin failed:", e); continue

        # 2. Submit result (ultra‑cheap gas)
        try:
            block  = w3.eth.get_block("pending")
            base   = block["baseFeePerGas"]
            tip    = Web3.to_wei(0.1, "gwei")              # 0.1 gwei
            maxfee = int(base * 1.03) + tip                # +3 %
            est    = contract.functions.submitResult(tid, smiles, cid).estimate_gas({"from": OWNER_ADDR})
            gas_limit = int(est * 1.05)                    # 5 % head‑room

            tx = contract.functions.submitResult(tid, smiles, cid).build_transaction({
                "from":                 OWNER_ADDR,
                "nonce":                w3.eth.get_transaction_count(OWNER_ADDR, "pending"),
                "gas":                  gas_limit,
                "maxPriorityFeePerGas": tip,
                "maxFeePerGas":         maxfee,
                "chainId":              chain_id
            })

            signed  = w3.eth.account.sign_transaction(tx, OWNER_KEY)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            print(f"   tx sent → {tx_hash.hex()}  gas={gas_limit}")

            rcpt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            status = "success" if rcpt.status == 1 else "revert"
            print(f"   ✓ submitResult {status} (block {rcpt.blockNumber})")
        except Exception as e:
            print("   ✖ submitResult failed:", e)

    time.sleep(5)
