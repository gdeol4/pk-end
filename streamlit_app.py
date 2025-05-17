import os
import json
import requests
from web3 import Web3
import streamlit as st

# ──────────────────────────  CONFIG  ──────────────────────────
WEB3_PROVIDER_URI = "https://ethereum-sepolia.publicnode.com"
CONTRACT_ADDRESS  = "0xBc43a97906e2061De0B92CaFC78e1912CE558012"

ACCOUNT_ADDRESS   = "0xA9060179b16Cfddc66002B3B68714A84739EA371"
PRIVATE_KEY       = "e326b930fa1669cb142f9822c8b25dbfb3ff9d59d8cb360f7e17566ff5b70f35"

CHAIN_ID = 11155111  # Sepolia

# ───────────────────────  CONNECT WEB3  ───────────────────────
web3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER_URI, request_kwargs={"timeout": 30}))
if not web3.is_connected():
    st.error("Unable to connect to Sepolia RPC.")
    st.stop()

# ─────────────────────────  CONTRACT ABI  ─────────────────────
contract_abi = [
    {
        "inputs":[{"internalType":"string","name":"disease","type":"string"}],
        "name":"submitTarget",
        "outputs":[],
        "stateMutability":"nonpayable",
        "type":"function"
    },
    {
        "inputs":[],
        "name":"targetCount",
        "outputs":[{"internalType":"uint256","name":"","type":"uint256"}],
        "stateMutability":"view",
        "type":"function"
    },
    {                         # ← NEW
        "inputs":[],
        "name":"submissionFee",
        "outputs":[{"internalType":"uint256","name":"","type":"uint256"}],
        "stateMutability":"view",
        "type":"function"
    },
    {
        "inputs":[{"internalType":"uint256","name":"targetId","type":"uint256"}],
        "name":"getResult",
        "outputs":[
            {"internalType":"string","name":"ligandSMILES","type":"string"},
            {"internalType":"string","name":"ipfsHash",     "type":"string"},
            {"internalType":"uint256","name":"timestamp",   "type":"uint256"}
        ],
        "stateMutability":"view",
        "type":"function"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "internalType": "address", "name": "user",     "type": "address"},
            {"indexed": True,  "internalType": "uint256", "name": "targetId", "type": "uint256"},
            {"indexed": False, "internalType": "string",  "name": "target",   "type": "string"}
        ],
        "name": "TargetSubmitted",
        "type": "event"
    }
]


contract = web3.eth.contract(address=Web3.to_checksum_address(CONTRACT_ADDRESS),
                              abi=contract_abi)

# ──────────────────────────  STREAMLIT UI  ────────────────────
st.title("PolyKye Onchain Demo – Ligand Optimization via Blockchain & IPFS")

if "last_target_id" not in st.session_state:
    st.session_state.last_target_id = None

disease_input = st.text_input("Enter a disease target to find an optimal ligand:", "")

# ───────────────────────  SUBMIT TARGET  ──────────────────────
if st.button("Submit Target"):
    if not disease_input.strip():
        st.warning("Please enter a valid disease name.")
    else:
        try:
            # fresh EIP‑1559 fees
            pending_block   = web3.eth.get_block("pending")
            base_fee        = pending_block["baseFeePerGas"]
            max_priority    = web3.to_wei(2, "gwei")
            max_fee         = int(base_fee * 1.5) + max_priority   # 1.5 × base

            txn = contract.functions.submitTarget(disease_input).build_transaction({
                "from":                 ACCOUNT_ADDRESS,
                "nonce":                web3.eth.get_transaction_count(ACCOUNT_ADDRESS, "pending"),
                "gas":                  250_000,            # plenty for submitTarget
                "maxPriorityFeePerGas": max_priority,
                "maxFeePerGas":         max_fee,
                "chainId":              CHAIN_ID
            })

            signed_txn = web3.eth.account.sign_transaction(txn, PRIVATE_KEY)
            tx_hash    = web3.eth.send_raw_transaction(signed_txn.raw_transaction)
            receipt    = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

            if receipt.status != 1:
                st.error(f"Transaction reverted in block {receipt.blockNumber}.")
            else:
                events = contract.events.TargetSubmitted().process_receipt(receipt)
                target_id = events[0]["args"]["targetId"] if events else contract.functions.targetCount().call() - 1
                st.session_state.last_target_id = target_id
                st.success(f"Submitted '{disease_input}' (target ID {target_id}).")
                st.info("Wait a minute, then click **Check Result**.")
        except Exception as e:
            st.error(f"Error submitting target: {e}")

# ───────────────────────  CHECK RESULT  ───────────────────────
if st.session_state.last_target_id is not None:
    target_id = st.session_state.last_target_id
    if st.button("Check Result"):
        try:
            smiles, ipfs_hash, ts = contract.functions.getResult(target_id).call()
            if smiles:
                st.subheader("Optimized Ligand Result")
                st.markdown(f"**Optimized SMILES:** `{smiles}`")
                st.markdown(f"**Timestamp:** {ts}")
                if ipfs_hash:
                    url = f"https://gateway.pinata.cloud/ipfs/{ipfs_hash}"
                    st.markdown(f"**IPFS JSON:** [{ipfs_hash}]({url})")

                    # pull the JSON to show details (optional)
                    try:
                        data = requests.get(url, timeout=15).json()
                        opt   = data.get("optimized", {})
                        st.markdown(f"**Ligand Name:** {opt.get('name','–')}")
                        st.markdown(f"**IC50:** {opt.get('optimized_ic50','–')}")
                        st.markdown(f"**Rationale:** {data.get('rationale','–')}")
                    except Exception:
                        st.info("Pinned JSON not yet reachable via gateway.")
            else:
                st.info("Result not yet available. Please try again later.")
        except Exception as e:
            st.error(f"Error fetching result: {e}")
