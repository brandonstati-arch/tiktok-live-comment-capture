"""Introspeccion del proto real de TikTokLive: confirma los nombres de campo
que realmente existen en la version instalada. No lee el README (desactualizado)."""
import json

from TikTokLive.events import CommentEvent, GiftEvent, ConnectEvent
from TikTokLive.proto import User
from TikTokLive.proto.custom_proto import ExtendedUser, ExtendedGift
import TikTokLive.proto as P


def fields(cls):
    """betterproto2 0.9+ ya no expone _betterproto.fields -> usamos dataclass fields."""
    f = getattr(cls, "__dataclass_fields__", None)
    if f:
        return sorted(f.keys())
    try:
        return sorted(fld.name for fld in cls._betterproto.fields)
    except Exception as e:  # pragma: no cover
        return f"<no disponible: {e}>"


out = {}
out["CommentEvent.fields"] = fields(CommentEvent)
out["GiftEvent.fields"] = fields(GiftEvent)
out["ConnectEvent.fields"] = fields(ConnectEvent)
out["User.fields"] = fields(User)
out["ExtendedUser.fields"] = fields(ExtendedUser)
out["ExtendedGift.fields"] = fields(ExtendedGift)

for name in ("CommonMessageData", "UserIdentity", "FollowInfo", "BadgeStruct", "Image", "UserBadge"):
    cls = getattr(P, name, None)
    out[f"{name}.fields"] = fields(cls) if cls is not None else "<no existe>"

out["ExtendedUser.attrs"] = sorted(a for a in dir(ExtendedUser) if not a.startswith("_"))

print(json.dumps(out, indent=1, ensure_ascii=False))
