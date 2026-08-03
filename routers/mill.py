"""
Over The Fence — Mill backend
Handles: communities, channels, direct messages, group DMs, messages, people
search, and discussion forums.

All tables are auto-created (IF NOT EXISTS) so no migration script is needed.
Auth: reads x-people-id header (set by the frontend alongside Bearer token).
"""
import re
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from typing import Optional
from datetime import datetime

router = APIRouter(prefix="/api/admin/mill", tags=["mill"])

# ── Auto-create tables ────────────────────────────────────────────────────────

with engine.begin() as _c:
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OTFCommunities')
        CREATE TABLE OTFCommunities (
            CommunityID   INT IDENTITY(1,1) PRIMARY KEY,
            Name          NVARCHAR(120) NOT NULL,
            Description   NVARCHAR(500) NULL,
            IsPublic      BIT NOT NULL DEFAULT 1,
            CreatedBy     INT NULL,
            CreatedAt     DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OTFCommunityMembers')
        CREATE TABLE OTFCommunityMembers (
            MemberID      INT IDENTITY(1,1) PRIMARY KEY,
            CommunityID   INT NOT NULL,
            PeopleID      INT NOT NULL,
            JoinedAt      DATETIME NOT NULL DEFAULT GETDATE(),
            CONSTRAINT UQ_OTFCommMem UNIQUE (CommunityID, PeopleID)
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OTFChannels')
        CREATE TABLE OTFChannels (
            ChannelID     INT IDENTITY(1,1) PRIMARY KEY,
            CommunityID   INT NULL,
            Name          NVARCHAR(120) NULL,
            Description   NVARCHAR(500) NULL,
            ChannelType   VARCHAR(20) NOT NULL DEFAULT 'text',
            CreatedBy     INT NULL,
            CreatedAt     DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OTFChannelMembers')
        CREATE TABLE OTFChannelMembers (
            ID            INT IDENTITY(1,1) PRIMARY KEY,
            ChannelID     INT NOT NULL,
            PeopleID      INT NOT NULL,
            LastReadAt    DATETIME NULL,
            JoinedAt      DATETIME NOT NULL DEFAULT GETDATE(),
            CONSTRAINT UQ_OTFChanMem UNIQUE (ChannelID, PeopleID)
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OTFMessages')
        CREATE TABLE OTFMessages (
            MessageID     INT IDENTITY(1,1) PRIMARY KEY,
            ChannelID     INT NOT NULL,
            SenderID      INT NOT NULL,
            SenderName    NVARCHAR(120) NULL,
            Body          NVARCHAR(MAX) NOT NULL,
            IsDeleted     BIT NOT NULL DEFAULT 0,
            CreatedAt     DATETIME NOT NULL DEFAULT GETDATE(),
            EditedAt      DATETIME NULL
        )
    """))
    # ── Forums ───────────────────────────────────────────────────────────────
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OTFForumCategories')
        CREATE TABLE OTFForumCategories (
            CategoryID    INT IDENTITY(1,1) PRIMARY KEY,
            Name          NVARCHAR(120) NOT NULL,
            Description   NVARCHAR(500) NULL,
            Icon          VARCHAR(40) NULL,
            SortOrder     INT NOT NULL DEFAULT 0,
            CreatedAt     DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OTFForumThreads')
        CREATE TABLE OTFForumThreads (
            ThreadID      INT IDENTITY(1,1) PRIMARY KEY,
            CategoryID    INT NOT NULL,
            Title         NVARCHAR(300) NOT NULL,
            Body          NVARCHAR(MAX) NOT NULL,
            AuthorID      INT NOT NULL,
            AuthorName    NVARCHAR(120) NULL,
            IsPinned      BIT NOT NULL DEFAULT 0,
            IsLocked      BIT NOT NULL DEFAULT 0,
            ViewCount     INT NOT NULL DEFAULT 0,
            ReplyCount    INT NOT NULL DEFAULT 0,
            LastPostAt    DATETIME NULL,
            CreatedAt     DATETIME NOT NULL DEFAULT GETDATE()
        )
    """))
    _c.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OTFForumPosts')
        CREATE TABLE OTFForumPosts (
            PostID        INT IDENTITY(1,1) PRIMARY KEY,
            ThreadID      INT NOT NULL,
            AuthorID      INT NOT NULL,
            AuthorName    NVARCHAR(120) NULL,
            Body          NVARCHAR(MAX) NOT NULL,
            IsDeleted     BIT NOT NULL DEFAULT 0,
            CreatedAt     DATETIME NOT NULL DEFAULT GETDATE(),
            EditedAt      DATETIME NULL
        )
    """))
    # Add IsFlagged column to threads/posts if not present (idempotent)
    _c.execute(text("""
        IF NOT EXISTS (
            SELECT * FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME='OTFForumThreads' AND COLUMN_NAME='IsFlagged'
        )
        ALTER TABLE OTFForumThreads ADD IsFlagged BIT NOT NULL DEFAULT 0
    """))
    _c.execute(text("""
        IF NOT EXISTS (
            SELECT * FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME='OTFForumPosts' AND COLUMN_NAME='IsFlagged'
        )
        ALTER TABLE OTFForumPosts ADD IsFlagged BIT NOT NULL DEFAULT 0
    """))
    # Seed default forum categories if empty
    _c.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM OTFForumCategories)
        BEGIN
            INSERT INTO OTFForumCategories (Name, Description, Icon, SortOrder) VALUES
            ('Crop Talk',        'Planting, growing, harvesting — all things crops',         'crop',       1),
            ('Livestock Corner', 'Cattle, swine, poultry, sheep, and more',                  'livestock',  2),
            ('Equipment',        'Machinery advice, repairs, buying/selling tips',            'equipment',  3),
            ('Markets & Prices', 'Commodity prices, buyer/seller tips, market trends',        'market',     4),
            ('Sustainability',   'Cover crops, soil health, carbon, conservation programs',  'leaf',       5),
            ('Farm Life',        'General farming lifestyle, community, off-topic',          'farm',       6)
        END
    """))


# ── Content moderation ────────────────────────────────────────────────────────

# (word, regex_pattern) — patterns use word boundaries to avoid false positives
_PROFANITY: list[tuple[str, str]] = [
    ("f***",     r'\bf+[u\*]+c+k\w*'),
    ("s***",     r'\bsh[i1!]+t\w*'),
    ("a**hole",  r'\ba+s+h[o0]+l+[e3]+s?\b'),
    ("b****rd",  r'\bbast[a@]+rds?\b'),
    ("b****",    r'\bb[i1!]+tch\w*'),
    ("c***",     r'\bcunts?\b'),
    ("c***",     r'\bc[o0]+cks?\b'),
    ("d***",     r'\bd[i1!]+cks?\b'),
    ("p****",    r'\bpuss[yi]+\b'),
    ("m***f***", r'\bm[o0]+th[e3]rf+[u\*]+ck\w*'),
    ("f***ot",   r'\bf[a@]+gg?[o0]+ts?\b'),
    ("r*tard",   r'\br[e3]t[a@]rds?\b'),
    ("wh**e",    r'\bwh[o0]+r[e3]+s?\b'),
    ("sl**",     r'\bsluts?\b'),
    ("tw**",     r'\btwats?\b'),
    ("p***",     r'\bp[i1!]+ss\w*'),
    ("d**n",     r'\bgodd[a@]+mn\b'),
    ("d**bass",  r'\bdumb[a@]+ss\w*'),
    ("j**kass",  r'\bjack[a@]+ss\w*'),
    ("d**shit",  r'\bdipsh[i1!]+t\b'),
    ("bulls***", r'\bbullsh[i1!]+t\b'),
    ("m*fo",     r'\bm[o0]+f[o0]+\b'),
    ("n*****",   r'\bn[i1!]+gg[ae]rs?\b'),
    ("cr**",     r'\bcr[a@]+p\b'),
]

_COMPILED_PROFANITY = [
    (replacement, re.compile(pattern, re.IGNORECASE))
    for replacement, pattern in _PROFANITY
]

_DANGER_PATTERNS = [
    re.compile(r'\b(kill|murder|shoot|stab|assault)\s+\w*\s*(you|him|her|them|yourself|myself|everyone)\b', re.I),
    re.compile(r'\b(gonna|going\s+to|will)\s+\w*\s*(kill|hurt|harm|attack|rape)\b', re.I),
    re.compile(r'\b(bomb|explosive|terrorism|terrorist\s+attack|ied)\b', re.I),
    re.compile(r'\b(rape|molest)\s+(you|him|her|them|children|kids|a\s+child)\b', re.I),
    re.compile(r'\bdie\s+(bitch|today|now|you)\b', re.I),
    re.compile(r'\bI\s+will\s+find\s+(you|your\s+address|where\s+you\s+live)\b', re.I),
    re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),           # SSN pattern
]


def _redact_profanity(text: str) -> str:
    """Replace profane words with redacted equivalents."""
    for replacement, pattern in _COMPILED_PROFANITY:
        text = pattern.sub(replacement, text)
    return text


def _is_dangerous(text: str) -> bool:
    """Return True if text contains threatening or dangerous content."""
    return any(p.search(text) for p in _DANGER_PATTERNS)


def _moderate(text: str) -> tuple[str, bool]:
    """
    Returns (moderated_text, is_flagged).
    Profanity is redacted automatically; dangerous content sets is_flagged=True.
    """
    cleaned = _redact_profanity(text)
    flagged = _is_dangerous(text)
    return cleaned, flagged


# ── Auth helper ───────────────────────────────────────────────────────────────

def _me(x_people_id: Optional[str] = Header(default=None)) -> int:
    try:
        pid = int(x_people_id or 0)
    except Exception:
        pid = 0
    if not pid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return pid


def _name(people_id: int, db: Session) -> str:
    row = db.execute(
        text("SELECT TOP 1 FirstName + ' ' + LastName FROM People WHERE PeopleID=:p"),
        {"p": people_id}
    ).scalar()
    return row or f"User {people_id}"


# ── People search ─────────────────────────────────────────────────────────────

@router.get("/people")
def search_people(q: str = "", db: Session = Depends(get_db), me: int = Depends(_me)):
    pattern = f"%{q}%" if q else "%"
    rows = db.execute(text("""
        SELECT TOP 30 p.PeopleID,
               p.FirstName + ' ' + p.LastName AS Name,
               b.BusinessName AS TeamCompany
        FROM People p
        LEFT JOIN Business b ON b.BusinessID = (
            SELECT TOP 1 BusinessID FROM People WHERE PeopleID = p.PeopleID
        )
        WHERE (p.FirstName + ' ' + p.LastName) LIKE :pat
          AND p.PeopleID <> :me
        ORDER BY p.FirstName, p.LastName
    """), {"pat": pattern, "me": me}).fetchall()
    return [dict(r._mapping) for r in rows]


# ── Communities ───────────────────────────────────────────────────────────────

@router.get("/communities")
def list_communities(db: Session = Depends(get_db), me: int = Depends(_me)):
    rows = db.execute(text("""
        SELECT c.CommunityID, c.Name, c.Description, c.IsPublic, c.CreatedAt,
               (SELECT COUNT(*) FROM OTFCommunityMembers m WHERE m.CommunityID=c.CommunityID) AS MemberCount,
               CASE WHEN EXISTS(SELECT 1 FROM OTFCommunityMembers m2
                                WHERE m2.CommunityID=c.CommunityID AND m2.PeopleID=:me) THEN 1 ELSE 0 END AS IsMember
        FROM OTFCommunities c
        WHERE c.IsPublic=1 OR EXISTS(SELECT 1 FROM OTFCommunityMembers m3
                                      WHERE m3.CommunityID=c.CommunityID AND m3.PeopleID=:me)
        ORDER BY c.Name
    """), {"me": me}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/communities")
def create_community(body: dict, db: Session = Depends(get_db), me: int = Depends(_me)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    row = db.execute(text("""
        INSERT INTO OTFCommunities (Name, Description, IsPublic, CreatedBy)
        OUTPUT INSERTED.CommunityID
        VALUES (:n, :d, :pub, :me)
    """), {"n": name, "d": body.get("description"), "pub": 1 if body.get("isPublic", True) else 0, "me": me}).fetchone()
    cid = row[0]
    db.execute(text("INSERT INTO OTFCommunityMembers (CommunityID, PeopleID) VALUES (:c, :p)"), {"c": cid, "p": me})
    # Create a default #general channel
    db.execute(text("""
        INSERT INTO OTFChannels (CommunityID, Name, Description, ChannelType, CreatedBy)
        VALUES (:c, 'general', 'General discussion', 'text', :me)
    """), {"c": cid, "me": me})
    db.commit()
    return {"communityId": cid}


@router.post("/communities/{community_id}/join")
def join_community(community_id: int, db: Session = Depends(get_db), me: int = Depends(_me)):
    exists = db.execute(text("SELECT 1 FROM OTFCommunities WHERE CommunityID=:c"), {"c": community_id}).scalar()
    if not exists:
        raise HTTPException(status_code=404, detail="Community not found")
    try:
        db.execute(text("INSERT INTO OTFCommunityMembers (CommunityID, PeopleID) VALUES (:c, :p)"), {"c": community_id, "p": me})
        db.commit()
    except Exception:
        db.rollback()
    return {"ok": True}


# ── Channels ──────────────────────────────────────────────────────────────────

@router.get("/channels")
def list_channels(db: Session = Depends(get_db), me: int = Depends(_me)):
    rows = db.execute(text("""
        SELECT ch.ChannelID, ch.CommunityID, ch.Name, ch.Description, ch.ChannelType,
               (SELECT TOP 1 Body FROM OTFMessages WHERE ChannelID=ch.ChannelID ORDER BY CreatedAt DESC) AS LastMessage,
               (SELECT TOP 1 CreatedAt FROM OTFMessages WHERE ChannelID=ch.ChannelID ORDER BY CreatedAt DESC) AS LastMessageAt,
               (SELECT COUNT(*) FROM OTFMessages m
                WHERE m.ChannelID=ch.ChannelID AND m.IsDeleted=0
                  AND m.CreatedAt > ISNULL((SELECT LastReadAt FROM OTFChannelMembers
                                            WHERE ChannelID=ch.ChannelID AND PeopleID=:me), '2000-01-01')
               ) AS UnreadCount,
               (SELECT STRING_AGG(p2.FirstName + ' ' + p2.LastName, ', ')
                FROM OTFChannelMembers cm2
                JOIN People p2 ON p2.PeopleID=cm2.PeopleID
                WHERE cm2.ChannelID=ch.ChannelID AND cm2.PeopleID<>:me
               ) AS DmPartnerNames
        FROM OTFChannels ch
        INNER JOIN OTFChannelMembers cm ON cm.ChannelID=ch.ChannelID AND cm.PeopleID=:me
        ORDER BY LastMessageAt DESC
    """), {"me": me}).fetchall()
    return {"channels": [dict(r._mapping) for r in rows]}


@router.get("/channels/{channel_id}/messages")
def get_messages(channel_id: int, limit: int = 50, db: Session = Depends(get_db), me: int = Depends(_me)):
    # Mark as read
    db.execute(text("""
        UPDATE OTFChannelMembers SET LastReadAt=GETDATE()
        WHERE ChannelID=:ch AND PeopleID=:me
    """), {"ch": channel_id, "me": me})
    db.commit()
    rows = db.execute(text("""
        SELECT TOP (:lim) MessageID, ChannelID, SenderID, SenderName, Body, IsDeleted, CreatedAt, EditedAt
        FROM OTFMessages
        WHERE ChannelID=:ch
        ORDER BY CreatedAt ASC
    """), {"ch": channel_id, "lim": limit}).fetchall()
    return {"messages": [dict(r._mapping) for r in rows]}


@router.post("/channels/{channel_id}/messages")
def send_message(channel_id: int, body: dict, db: Session = Depends(get_db), me: int = Depends(_me)):
    text_body = (body.get("body") or "").strip()
    if not text_body:
        raise HTTPException(status_code=400, detail="Message body required")
    sender_name = _name(me, db)
    row = db.execute(text("""
        INSERT INTO OTFMessages (ChannelID, SenderID, SenderName, Body)
        OUTPUT INSERTED.MessageID, INSERTED.CreatedAt
        VALUES (:ch, :me, :name, :body)
    """), {"ch": channel_id, "me": me, "name": sender_name, "body": text_body}).fetchone()
    db.commit()
    return {"messageId": row[0], "createdAt": row[1].isoformat()}


# ── Direct Messages ───────────────────────────────────────────────────────────

def _find_or_create_dm(me: int, partner_ids: list[int], db: Session) -> int:
    """Find an existing DM channel between these exact people, or create one."""
    all_ids = sorted(set([me] + partner_ids))
    chan_type = "dm" if len(all_ids) == 2 else "group_dm"

    # Look for an existing channel where all members match exactly
    for pid in all_ids:
        cands = db.execute(text("""
            SELECT ChannelID FROM OTFChannelMembers WHERE PeopleID=:p
            AND ChannelID IN (SELECT ChannelID FROM OTFChannels WHERE ChannelType IN ('dm','group_dm'))
        """), {"p": pid}).fetchall()
        for (cid,) in cands:
            members = sorted(r[0] for r in db.execute(
                text("SELECT PeopleID FROM OTFChannelMembers WHERE ChannelID=:c"), {"c": cid}
            ).fetchall())
            if members == all_ids:
                return cid

    # Create new channel
    row = db.execute(text("""
        INSERT INTO OTFChannels (ChannelType, CreatedBy)
        OUTPUT INSERTED.ChannelID
        VALUES (:ct, :me)
    """), {"ct": chan_type, "me": me}).fetchone()
    cid = row[0]
    for pid in all_ids:
        db.execute(text("INSERT INTO OTFChannelMembers (ChannelID, PeopleID) VALUES (:c, :p)"), {"c": cid, "p": pid})
    db.commit()
    return cid


@router.post("/dm")
def start_dm(body: dict, db: Session = Depends(get_db), me: int = Depends(_me)):
    target = body.get("targetPeopleId")
    members = body.get("memberIds") or []
    if target:
        partner_ids = [int(target)]
    elif members:
        partner_ids = [int(x) for x in members]
    else:
        raise HTTPException(status_code=400, detail="targetPeopleId or memberIds required")

    cid = _find_or_create_dm(me, partner_ids, db)
    return {"channelId": cid}


# ── Open a DM from another module (equipment inquiry / food wanted response) ──

@router.post("/dm/from-module")
def dm_from_module(body: dict, db: Session = Depends(get_db), me: int = Depends(_me)):
    """
    Called when a user clicks 'Message Seller' on an equipment listing or
    'Contact Poster' on a food wanted ad. Creates the DM and optionally sends
    a pre-populated first message.
    Accepts targetPeopleId OR targetBusinessId (will look up primary contact).
    """
    target_id = body.get("targetPeopleId")
    if not target_id and body.get("targetBusinessId"):
        row = db.execute(text(
            "SELECT TOP 1 PeopleID FROM People WHERE BusinessID=:bid ORDER BY PeopleID"
        ), {"bid": int(body["targetBusinessId"])}).first()
        if row:
            target_id = row[0]
    if not target_id:
        raise HTTPException(status_code=400, detail="targetPeopleId or targetBusinessId required")

    cid = _find_or_create_dm(me, [int(target_id)], db)

    opening_msg = (body.get("message") or "").strip()
    if opening_msg:
        sender_name = _name(me, db)
        db.execute(text("""
            INSERT INTO OTFMessages (ChannelID, SenderID, SenderName, Body)
            VALUES (:ch, :me, :name, :body)
        """), {"ch": cid, "me": me, "name": sender_name, "body": opening_msg})
        db.commit()

    return {"channelId": cid}


# ── Forums ────────────────────────────────────────────────────────────────────

@router.get("/forums")
def list_forum_categories(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT fc.CategoryID, fc.Name, fc.Description, fc.Icon, fc.SortOrder,
               (SELECT COUNT(*) FROM OTFForumThreads t WHERE t.CategoryID=fc.CategoryID) AS ThreadCount,
               (SELECT TOP 1 t2.Title FROM OTFForumThreads t2
                WHERE t2.CategoryID=fc.CategoryID ORDER BY t2.CreatedAt DESC) AS LatestThreadTitle,
               (SELECT TOP 1 t2.CreatedAt FROM OTFForumThreads t2
                WHERE t2.CategoryID=fc.CategoryID ORDER BY t2.CreatedAt DESC) AS LatestThreadAt
        FROM OTFForumCategories fc
        ORDER BY fc.SortOrder
    """)).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/forums/{category_id}/threads")
def list_threads(category_id: int, page: int = 1, db: Session = Depends(get_db)):
    offset = (page - 1) * 20
    rows = db.execute(text("""
        SELECT ThreadID, CategoryID, Title, AuthorName, IsPinned, IsLocked,
               ViewCount, ReplyCount, LastPostAt, CreatedAt
        FROM OTFForumThreads
        WHERE CategoryID=:cat
        ORDER BY IsPinned DESC, ISNULL(LastPostAt, CreatedAt) DESC
        OFFSET :off ROWS FETCH NEXT 20 ROWS ONLY
    """), {"cat": category_id, "off": offset}).fetchall()
    total = db.execute(text("SELECT COUNT(*) FROM OTFForumThreads WHERE CategoryID=:cat"), {"cat": category_id}).scalar()
    return {"threads": [dict(r._mapping) for r in rows], "total": total, "page": page}


@router.post("/forums/{category_id}/threads")
def create_thread(category_id: int, body: dict, db: Session = Depends(get_db), me: int = Depends(_me)):
    title = (body.get("title") or "").strip()
    content = (body.get("body") or "").strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="Title and body required")
    title_clean, title_flagged   = _moderate(title)
    content_clean, body_flagged  = _moderate(content)
    is_flagged = title_flagged or body_flagged
    if is_flagged:
        raise HTTPException(
            status_code=422,
            detail="Your post contains content that violates community guidelines and cannot be published."
        )
    author_name = _name(me, db)
    row = db.execute(text("""
        INSERT INTO OTFForumThreads (CategoryID, Title, Body, AuthorID, AuthorName, IsFlagged, LastPostAt)
        OUTPUT INSERTED.ThreadID
        VALUES (:cat, :title, :body, :me, :name, :flag, GETDATE())
    """), {"cat": category_id, "title": title_clean, "body": content_clean,
           "me": me, "name": author_name, "flag": 0}).fetchone()
    db.commit()
    return {"threadId": row[0]}


@router.get("/forums/threads/{thread_id}")
def get_thread(thread_id: int, db: Session = Depends(get_db)):
    # Increment view count
    db.execute(text("UPDATE OTFForumThreads SET ViewCount=ViewCount+1 WHERE ThreadID=:t"), {"t": thread_id})
    db.commit()
    thread = db.execute(text("""
        SELECT ThreadID, CategoryID, Title, Body, AuthorID, AuthorName,
               IsPinned, IsLocked, ViewCount, ReplyCount, LastPostAt, CreatedAt
        FROM OTFForumThreads WHERE ThreadID=:t
    """), {"t": thread_id}).fetchone()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    posts = db.execute(text("""
        SELECT PostID, ThreadID, AuthorID, AuthorName, Body, IsDeleted, CreatedAt, EditedAt
        FROM OTFForumPosts
        WHERE ThreadID=:t AND IsDeleted=0
        ORDER BY CreatedAt ASC
    """), {"t": thread_id}).fetchall()
    return {
        "thread": dict(thread._mapping),
        "posts": [dict(r._mapping) for r in posts],
    }


@router.post("/forums/threads/{thread_id}/posts")
def reply_to_thread(thread_id: int, body: dict, db: Session = Depends(get_db), me: int = Depends(_me)):
    content = (body.get("body") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Body required")
    thread = db.execute(text("SELECT IsLocked FROM OTFForumThreads WHERE ThreadID=:t"), {"t": thread_id}).fetchone()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    if thread.IsLocked:
        raise HTTPException(status_code=403, detail="Thread is locked")
    content_clean, is_flagged = _moderate(content)
    if is_flagged:
        raise HTTPException(
            status_code=422,
            detail="Your reply contains content that violates community guidelines and cannot be published."
        )
    author_name = _name(me, db)
    row = db.execute(text("""
        INSERT INTO OTFForumPosts (ThreadID, AuthorID, AuthorName, Body, IsFlagged)
        OUTPUT INSERTED.PostID
        VALUES (:t, :me, :name, :body, :flag)
    """), {"t": thread_id, "me": me, "name": author_name, "body": content_clean, "flag": 0}).fetchone()
    db.execute(text("""
        UPDATE OTFForumThreads
        SET ReplyCount=ReplyCount+1, LastPostAt=GETDATE()
        WHERE ThreadID=:t
    """), {"t": thread_id})
    db.commit()
    return {"postId": row[0]}
