"""
Modo demostración: genera eventos sintéticos con el proto REAL y los inyecta
por los handlers reales de la sesión.

Para qué sirve: validar interfaz, CSV y Excel sin depender de que haya un
directo en vivo en ese momento. Es la prueba que se corre siempre antes de
decir que la aplicación está lista.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone

from TikTokLive.events import CommentEvent, GiftEvent
from TikTokLive.proto import CommonMessageData, UserIdentity
from TikTokLive.proto.custom_proto import ExtendedGift, ExtendedUser
from TikTokLiveProto.v3.webcast.model.base.user import BadgeStruct, PrivilegeLogExtra
from TikTokLiveProto.v3.webcast.model.data import BadgeSceneType

FAKE_USERS = [
    ("ana_tt", "Ana Torres", 7300000000001, "ES"),
    ("el_marce", "Marcelo Ríos", 7300000000002, "ES"),
    ("lucia.live", "Lucía Fernández", 7300000000003, "ES"),
    ("dani_ar", "Daniela Arias", 7300000000004, "ES"),
    ("topgifter99", "Carlos Núñez", 7300000000005, "ES"),
    ("mod_sofia", "Sofía Moderadora", 7300000000006, "ES"),
    ("jorge_mx", "Jorge Ramírez", 7300000000007, "MX"),
    ("nuria_bcn", "Núria Puig", 7300000000008, "ES"),
]

FAKE_COMMENTS = [
    "¡Hola a todos! 👋",
    "Saludos desde Colombia 🇨🇴",
    "¿De qué trata el directo hoy?",
    "Primera vez por aquí, me quedo",
    "Jajaja no puede ser 😂",
    "¿Puedes repetir eso?",
    "Apoyando desde México 🇲🇽",
    "El audio se escucha perfecto",
    "¿Cuándo es el próximo directo?",
    "¡Qué buen contenido! 🔥",
    "Ya te seguí hace tiempo",
    "Saludos desde Argentina 🇦🇷",
    "¿Haces sorteos?",
    "Este tema me interesa mucho",
    "Muy buena explicación, gracias",
    "No me pierdo ninguno 💪",
    "¿Se puede participar?",
    "Un saludo desde España 🇪🇸",
    "Comparto el directo ahora mismo",
    "¿Cuál es tu opinión sobre eso?",
    "Espectacular como siempre",
    "Llegué tarde, ¿qué me perdí?",
    "Esto es oro puro",
    "¿Vas a subir el resumen?",
    "¡Vamos con todo! 🚀",
]

FAKE_GIFTS = [("Rosa", 5655, 1), ("TikTok", 5827, 1), ("Galaxia", 5587, 1000), ("Corazón", 5509, 5)]


def _badge(scene: str, level: int) -> BadgeStruct:
    """Construye una insignia con la forma REAL del proto instalado.

    Ojo: el enum mezcla nombres (`ADMIN`, `FANS`) con nombres con prefijo
    (`BADGE_SCENE_TYPE_RANK_LIST`), asi que se resuelven las dos formas.
    """
    badge = BadgeStruct()
    member = BadgeSceneType.__members__.get(scene) or BadgeSceneType.__members__.get(
        f"BADGE_SCENE_TYPE_{scene}"
    )
    badge.scene_type = member if member is not None else scene
    extra = PrivilegeLogExtra()
    extra.level = str(level)
    badge.privilege_log_extra = extra
    return badge


def _make_user(index: int, is_moderator: bool = False, is_subscriber: bool = False) -> ExtendedUser:
    handle, nickname, uid, _lang = FAKE_USERS[index % len(FAKE_USERS)]

    # Insignias: la fuente real de moderación, suscripción y niveles.
    badges: list[BadgeStruct] = [_badge("USER_GRADE", random.randint(1, 40))]
    if is_moderator:
        badges.append(_badge("ADMIN", 0))
    if is_subscriber:
        badges.append(_badge("SUBSCRIBER", random.randint(1, 20)))
        badges.append(_badge("FANS", random.randint(1, 30)))
    if index in (0, 2):
        badges.append(_badge("FRIENDS", 0))
    if index == 4:
        badges.append(_badge("RANK_LIST", random.randint(1, 50)))

    return ExtendedUser(
        id=uid,
        nickname=nickname,
        display_id=handle,
        sec_uid=f"MS4wLjABAAAA{uid}demo",
        is_subscribe=is_subscriber,
        is_follower=True,
        badge_list=badges,
    )


def _common(room_id: str, offset_ms: int = 0) -> CommonMessageData:
    # create_time en milisegundos: es la hora real de publicación del servidor.
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    return CommonMessageData(
        msg_id=str(random.getrandbits(62)),
        room_id=room_id,
        create_time=now_ms - offset_ms,
    )


def feed_demo(session, comments: int = 45, gifts: int = 8, should_stop=None) -> None:
    """Alimenta la sesión con comentarios y regalos simulados.

    `should_stop` es un callable opcional que se consulta en cada vuelta para
    poder cortar la demo a mitad (por ejemplo, al agotarse --segundos).
    """
    room_id = session.room_id or "0000000000000000000"

    for i in range(comments):
        if should_stop is not None and should_stop():
            return
        index = random.randrange(len(FAKE_USERS))
        is_mod = index == 5
        is_sub = index in (0, 4)
        user = _make_user(index, is_mod, is_sub)

        # Se repite un msg_id a propósito: el deduplicador debe descartarlo.
        msg_id = str(random.getrandbits(62))
        for attempt in range(2 if i in (3, 17) else 1):
            event = CommentEvent(
                common=CommonMessageData(
                    msg_id=msg_id,
                    room_id=room_id,
                    create_time=int(datetime.now(tz=timezone.utc).timestamp() * 1000)
                    - random.randint(120, 900),
                ),
                user=user,
                content=random.choice(FAKE_COMMENTS),
                content_language="es",
                user_identity=UserIdentity(
                    is_moderator_of_anchor=is_mod,
                    is_subscriber_of_anchor=is_sub,
                    is_follower_of_anchor=True,
                    is_mutual_following_with_anchor=is_sub,
                ),
            )
            session.ingest_event(event)

        time.sleep(random.uniform(0.25, 0.9))

    for _ in range(gifts):
        if should_stop is not None and should_stop():
            return
        user = _make_user(random.randrange(len(FAKE_USERS)))
        name, gift_id, diamonds = random.choice(FAKE_GIFTS)
        gift = ExtendedGift()
        gift.id = gift_id
        gift.name = name
        gift.diamond_count = diamonds
        gift.type = 1
        repeats = random.choice([1, 1, 1, 3, 5, 10])
        session.ingest_event(
            GiftEvent(
                common=_common(room_id),
                user=user,
                gift=gift,
                repeat_count=repeats,
                combo_count=repeats,
            )
        )
        time.sleep(random.uniform(0.3, 0.8))

    session.message = "Demostración finalizada · datos simulados"
    session._publish({"type": "status", "status": session.status()})
