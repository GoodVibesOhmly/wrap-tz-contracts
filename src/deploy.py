import json
from pathlib import Path
from typing import TypedDict

from pytezos import Contract

from src.ligo import PtzUtils
from src.minter import Minter
from src.token import Token


def _print_contract(addr):
    print(
        f'Successfully originated {addr}\n'
        f'Check out the contract at https://you.better-call.dev/delphinet/{addr}')


class TokenType(TypedDict):
    eth_contract: str
    eth_symbol: str
    symbol: str
    name: str
    decimals: int


class NftType(TypedDict):
    eth_contract: str
    eth_symbol: str
    symbol: str
    name: str


def _metadata_encode(content):
    meta_content = json.dumps(content, indent=2).encode().hex()
    meta_uri = str.encode("tezos-storage:content").hex()
    return {"": meta_uri, "content": meta_content}


def _metadata_encode_uri(uri):
    meta_uri = str.encode(uri).hex()
    return {"": meta_uri}


class Deploy(object):

    def __init__(self, client: PtzUtils):
        self.utils = client
        root_dir = Path(__file__).parent.parent / "michelson"
        self.minter_contract = Contract.from_file(root_dir / "minter.tz")
        self.quorum_contract = Contract.from_file(root_dir / "quorum.tz")
        self.fa2_contract = Contract.from_file(root_dir / "multi_asset.tz")
        self.nft_contract = Contract.from_file(root_dir / "nft.tz")

    def run(self, signers: dict[str, str], tokens: list[TokenType], nft: list[NftType], threshold=1):
        fa2 = self.fa2(tokens)
        nft_contracts = dict((v["eth_contract"][2:], self.nft(v)) for k, v in enumerate(nft))
        quorum = self._deploy_quorum(signers, threshold)
        minter = self._deploy_minter(quorum, tokens, fa2, nft_contracts)
        self._set_tokens_admin(minter, fa2, nft_contracts)
        self._confirm_admin(minter, fa2, nft_contracts)
        print(f"FA2 contract: {fa2}\nQuorum contract: {quorum}\nMinter contract: {minter}")

    def fa2(self, tokens: list[TokenType],
            meta_uri="https://gist.githubusercontent.com/BodySplash/"
                     "1a44558b64ce7c0edd77e1ba37d6d8bf/raw/4e1daa85bd1ae2bf4fd5b15fd6f92c5c43a5f2c4/multi_asset.json"):
        print("Deploying fa2")
        meta = _metadata_encode_uri(meta_uri)

        token_metadata = dict(
            [(k, {'token_id': k,
                  'token_info': {'decimals': str(v['decimals']).encode().hex(),
                                 'eth_contract': v['eth_contract'].encode().hex(),
                                 'eth_symbol': v['eth_symbol'].encode().hex(),
                                 'name': v['name'].encode().hex(),
                                 'symbol': v['symbol'].encode().hex()
                                 }}) for k, v in
             enumerate(tokens)])
        supply = dict([(k, 0) for k, v in enumerate(tokens)])
        initial_storage = {
            'admin': {
                'admin': self.utils.client.key.public_key_hash(),
                'pending_admin': None,
                'paused': {}
            },
            'assets': {
                'ledger': {},
                'operators': {},
                'token_metadata': token_metadata,
                'token_total_supply': supply
            },
            'metadata': meta
        }
        contract_id = self.utils.originate(self.fa2_contract, initial_storage)
        _print_contract(contract_id)
        return contract_id

    def nft(self, token: NftType, metadata_uri="https://gist.githubusercontent.com/BodySplash/"
                                               "05db57db07be61afd6fb568e5b48299e/raw/"
                                               "dbc8ff44a0f2251b0833bd5736f89a5af24aa00f/nft.json"):
        print("Deploying NFT")

        meta = _metadata_encode_uri(metadata_uri)

        generic_metadata = {'decimals': str(1).encode().hex(),
                            'eth_contract': token['eth_contract'].encode().hex(),
                            'eth_symbol': token['eth_symbol'].encode().hex(),
                            'name': token['name'].encode().hex(),
                            'symbol': token['symbol'].encode().hex()
                            }

        initial_storage = {
            'admin': {
                'admin': self.utils.client.key.public_key_hash(),
                'pending_admin': None,
                'paused': False
            },
            'assets': {
                'ledger': {},
                'operators': {},
                'token_info': generic_metadata
            },
            'metadata': meta
        }
        contract_id = self.utils.originate(self.nft_contract, initial_storage)
        _print_contract(contract_id)
        return contract_id

    def _set_tokens_admin(self, minter, fa2, nfts):
        token = Token(self.utils)
        token.set_admin(fa2, minter)
        [token.set_admin(v, minter) for (i, v) in nfts.items()]

    def _confirm_admin(self, minter, fa2_contract, nfts):
        minter_contract = Minter(self.utils)
        minter_contract.confirm_admin(minter, [v for (i, v) in nfts.items()] + [fa2_contract])

    def _deploy_minter(self, quorum_contract,
                       tokens: list[TokenType],
                       fa2_contract,
                       nft_contracts,
                       meta_uri="https://gist.githubusercontent.com/"
                                "BodySplash/"
                                "1106a10160cc8cc9d00ce9df369b884a/raw/"
                                "61c67c0b0481b4e0aa4d020d5ef411bf244af1d0/minter.json"):
        print("Deploying minter contract")
        fungible_tokens = dict((v["eth_contract"][2:], [fa2_contract, k]) for k, v in enumerate(tokens))
        metadata = _metadata_encode_uri(meta_uri)
        initial_storage = {
            "admin": {
                "administrator": self.utils.client.key.public_key_hash(),
                "signer": quorum_contract,
                "paused": False
            },
            "assets": {
                "erc20_tokens": fungible_tokens,
                "erc721_tokens": nft_contracts,
                "mints": {}
            },
            "governance": {
                "contract": self.utils.client.key.public_key_hash(),
                "fees_contract": self.utils.client.key.public_key_hash(),
                "erc20_wrapping_fees": 100,
                "erc20_unwrapping_fees": 100,
                "erc721_wrapping_fees": 500_000,
                "erc721_unwrapping_fees": 500_000
            },
            "metadata": metadata
        }

        contract_id = self.utils.originate(self.minter_contract, initial_storage)
        _print_contract(contract_id)
        return contract_id

    def _deploy_quorum(self, signers: dict[str, str],
                       threshold,
                       meta_uri="https://gist.githubusercontent.com/"
                                "BodySplash/2c10f6a73c7b0946dcc3ec2fc94bb6c6/"
                                "raw/"
                                "eb951d3845d43e0921242e8704d6bb1205fac2b1/"
                                "quorum.json"):
        metadata = _metadata_encode_uri(meta_uri)
        print("Deploying quorum contract")
        initial_storage = {
            "admin": self.utils.client.key.public_key_hash(),
            "threshold": threshold,
            "signers": signers,
            "metadata": metadata
        }
        contract_id = self.utils.originate(self.quorum_contract, initial_storage)
        _print_contract(contract_id)
        return contract_id
