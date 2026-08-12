from database.enums import AssetStatus


VALID_TRANSITIONS = {
    AssetStatus.DRAFT: {AssetStatus.EXTRACTED, AssetStatus.CANCELLED},
    AssetStatus.EXTRACTED: {AssetStatus.UNDERWRITTEN, AssetStatus.CANCELLED},
    AssetStatus.UNDERWRITTEN: {AssetStatus.LISTED, AssetStatus.CANCELLED},
    AssetStatus.LISTED: {AssetStatus.PARTIALLY_FUNDED, AssetStatus.CANCELLED},
    AssetStatus.PARTIALLY_FUNDED: {AssetStatus.FULLY_FUNDED, AssetStatus.CANCELLED},
    AssetStatus.FULLY_FUNDED: {AssetStatus.REPAID, AssetStatus.DEFAULTED},
    AssetStatus.REPAID: {AssetStatus.SETTLED},
    AssetStatus.SETTLED: set(),
    AssetStatus.DEFAULTED: set(),
    AssetStatus.CANCELLED: set(),
}


class InvalidStatusTransition(Exception):
    pass


def transition(asset, to_state):
    current = asset.status
    if to_state not in VALID_TRANSITIONS.get(current, set()):
        raise InvalidStatusTransition(
            f"Cannot transition asset {asset.id} from {current} to {to_state}"
        )
    asset.status = to_state
