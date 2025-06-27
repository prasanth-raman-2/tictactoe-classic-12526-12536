from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Body, Path, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from uuid import uuid4
from enum import Enum

# PUBLIC_INTERFACE
class PlayerSymbol(str, Enum):
    X = "X"
    O = "O"

# PUBLIC_INTERFACE
class UserSession(BaseModel):
    """A user session with just a nickname for this simple app's demo."""
    session_id: str = Field(..., description="Unique session identifier (UUID)")
    nickname: str = Field(..., min_length=2, max_length=32, description="Player's nickname")

# PUBLIC_INTERFACE
class UserLoginRequest(BaseModel):
    """Request model to create/start a user session (login)."""
    nickname: str = Field(..., min_length=2, max_length=32, description="Player's nickname")

# PUBLIC_INTERFACE
class GameStatus(str, Enum):
    waiting = "waiting"
    in_progress = "in_progress"
    finished = "finished"

# PUBLIC_INTERFACE
class MoveRequest(BaseModel):
    """Represents a player's move submission."""
    session_id: str = Field(..., description="Player's session id token")
    x: int = Field(..., ge=0, le=2, description="Row (0, 1, or 2)")
    y: int = Field(..., ge=0, le=2, description="Column (0, 1, or 2)")

# PUBLIC_INTERFACE
class MoveDetail(BaseModel):
    """A move made by a player."""
    move_number: int
    session_id: str
    x: int
    y: int
    symbol: PlayerSymbol

# PUBLIC_INTERFACE
class GameCreateRequest(BaseModel):
    """Request model to create a game."""
    session_id: str = Field(..., description="Creator's session id token")

# PUBLIC_INTERFACE
class GameJoinRequest(BaseModel):
    """Request model to join a game."""
    session_id: str = Field(..., description="Joining player's session id token")

# PUBLIC_INTERFACE
class GameState(BaseModel):
    """Details of a tic tac toe game."""
    game_id: str
    creator: UserSession
    opponent: Optional[UserSession] = None
    created_at: float
    moves: List[MoveDetail]
    board: List[List[Optional[PlayerSymbol]]]  # 3x3 Board
    status: GameStatus
    winner_session_id: Optional[str] = None
    current_turn: PlayerSymbol

# PUBLIC_INTERFACE
class LeaderboardEntry(BaseModel):
    nickname: str
    games_played: int
    games_won: int

# PUBLIC_INTERFACE
class LeaderboardResponse(BaseModel):
    leaderboard: List[LeaderboardEntry]

# In-memory storage for demo
user_sessions: Dict[str, UserSession] = {}
games: Dict[str, GameState] = {}
leaderboard_stats: Dict[str, LeaderboardEntry] = {}

# Helper for initializing a blank board
def empty_board():
    return [[None for _ in range(3)] for _ in range(3)]

# Create FastAPI instance with metadata
app = FastAPI(
    title="Tic Tac Toe Backend API",
    description="APIs for user/session management, game start/join, move handling, status retrieval, and leaderboard for Tic Tac Toe.",
    version="1.0.0",
    openapi_tags=[
        {"name": "auth", "description": "User login/session management"},
        {"name": "game", "description": "Game creation, joining, moves, and status"},
        {"name": "leaderboard", "description": "Leaderboard"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# PUBLIC_INTERFACE
@app.get("/", tags=["default"], summary="Health check endpoint")
def health_check():
    """API health check."""
    return {"message": "Healthy"}

# ---------- AUTH: Login/Session ----------

# PUBLIC_INTERFACE
@app.post("/login", response_model=UserSession, tags=["auth"], summary="Login or Create Session")
def login(request: UserLoginRequest):
    """
    Creates a user session for a nickname. Returns a session token.
    If nickname is reused, new session is created (sessions are stateless for simplicity).

    Parameters:
    - request: UserLoginRequest (JSON with `nickname`)

    Returns:
    - UserSession: session_id and nickname
    """
    session_id = str(uuid4())
    user_session = UserSession(session_id=session_id, nickname=request.nickname)
    user_sessions[session_id] = user_session
    # Add user to leaderboard if missing
    if request.nickname not in leaderboard_stats:
        leaderboard_stats[request.nickname] = LeaderboardEntry(
            nickname=request.nickname, games_played=0, games_won=0
        )
    return user_session

# ---------- GAME: Create, Join, Status, Move ----------

# PUBLIC_INTERFACE
@app.post("/game", response_model=GameState, tags=["game"], summary="Create a new Tic Tac Toe game")
def create_game(req: GameCreateRequest):
    """
    Creates a new game. The creator becomes player X.

    Parameters:
    - req: GameCreateRequest (with session_id)

    Returns:
    - GameState: Initial game state
    """
    session = user_sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    game_id = str(uuid4())
    state = GameState(
        game_id=game_id,
        creator=session,
        opponent=None,
        created_at=__import__("time").time(),
        moves=[],
        board=empty_board(),
        status=GameStatus.waiting,
        winner_session_id=None,
        current_turn=PlayerSymbol.X
    )
    games[game_id] = state
    return state

# PUBLIC_INTERFACE
@app.post("/game/{game_id}/join", response_model=GameState, tags=["game"], summary="Join an existing game")
def join_game(game_id: str = Path(..., description="Game id"),
              req: GameJoinRequest = Body(...)):
    """
    Join an open game. The joining player gets O.

    Parameters:
    - game_id: ID of the game to join
    - req: GameJoinRequest (with session_id)

    Returns:
    - GameState: State after joining
    """
    game = games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game.opponent:
        raise HTTPException(status_code=400, detail="Game already has an opponent")
    user = user_sessions.get(req.session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    if user.session_id == game.creator.session_id:
        raise HTTPException(status_code=400, detail="Creator cannot join own game")
    game.opponent = user
    game.status = GameStatus.in_progress
    return game

def is_board_full(board):
    return all(cell is not None for row in board for cell in row)

def get_other_symbol(symbol: PlayerSymbol) -> PlayerSymbol:
    return PlayerSymbol.O if symbol == PlayerSymbol.X else PlayerSymbol.X

def check_winner(board: List[List[Optional[PlayerSymbol]]]) -> Optional[PlayerSymbol]:
    # Rows/Cols/Diags
    lines = []
    lines.extend(board)  # rows
    lines.extend([[board[r][c] for r in range(3)] for c in range(3)])  # cols
    lines.append([board[i][i] for i in range(3)])  # diag
    lines.append([board[i][2-i] for i in range(3)])  # anti-diag
    for line in lines:
        if line[0] and all(cell == line[0] for cell in line):
            return line[0]
    return None

def update_leaderboard(winner_nick: Optional[str], creator_nick: str, opponent_nick: str):
    if creator_nick in leaderboard_stats:
        leaderboard_stats[creator_nick].games_played += 1
    else:
        leaderboard_stats[creator_nick] = LeaderboardEntry(nickname=creator_nick, games_played=1, games_won=0)
    if opponent_nick in leaderboard_stats:
        leaderboard_stats[opponent_nick].games_played += 1
    else:
        leaderboard_stats[opponent_nick] = LeaderboardEntry(nickname=opponent_nick, games_played=1, games_won=0)
    if winner_nick and winner_nick in leaderboard_stats:
        leaderboard_stats[winner_nick].games_won += 1

# PUBLIC_INTERFACE
@app.post("/game/{game_id}/move", response_model=GameState, tags=["game"], summary="Submit a move to a game")
def submit_move(game_id: str = Path(..., description="Game id"), req: MoveRequest = Body(...)):
    """
    Submit a move in an ongoing game.

    Parameters:
    - game_id: ID of the game
    - req: MoveRequest (with session_id, x, y)

    Returns:
    - GameState: Updated game state
    """
    game = games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    if game.status != GameStatus.in_progress:
        raise HTTPException(status_code=400, detail="Game is not in progress")
    player_symbol = None
    if req.session_id == game.creator.session_id:
        player_symbol = PlayerSymbol.X
    elif game.opponent and req.session_id == game.opponent.session_id:
        player_symbol = PlayerSymbol.O
    else:
        raise HTTPException(status_code=401, detail="You are not a player in this game")
    if game.current_turn != player_symbol:
        raise HTTPException(status_code=400, detail="Not your turn")
    if not (0 <= req.x <= 2 and 0 <= req.y <= 2):
        raise HTTPException(status_code=422, detail="Coordinates out of range")
    if game.board[req.x][req.y] is not None:
        raise HTTPException(status_code=400, detail="Cell already occupied")
    # Apply move
    move_number = len(game.moves) + 1
    move = MoveDetail(
        move_number=move_number,
        session_id=req.session_id,
        x=req.x,
        y=req.y,
        symbol=player_symbol
    )
    game.board[req.x][req.y] = player_symbol
    game.moves.append(move)
    # Check game status
    winner_symbol = check_winner(game.board)
    if winner_symbol:
        game.status = GameStatus.finished
        if winner_symbol == PlayerSymbol.X:
            game.winner_session_id = game.creator.session_id
            winner_nick = game.creator.nickname
        else:
            game.winner_session_id = (game.opponent.session_id if game.opponent else None)
            winner_nick = (game.opponent.nickname if game.opponent else None)
        update_leaderboard(
            winner_nick=winner_nick,
            creator_nick=game.creator.nickname,
            opponent_nick=(game.opponent.nickname if game.opponent else "")
        )
    elif is_board_full(game.board):
        game.status = GameStatus.finished
        game.winner_session_id = None
        update_leaderboard(
            winner_nick=None,
            creator_nick=game.creator.nickname,
            opponent_nick=(game.opponent.nickname if game.opponent else "")
        )
    else:
        game.current_turn = get_other_symbol(player_symbol)
    return game

# PUBLIC_INTERFACE
@app.get("/game/{game_id}/status", response_model=GameState, tags=["game"], summary="Fetch game status and board state")
def fetch_game_status(game_id: str = Path(..., description="Game id")):
    """
    Get the current game board, participants, and state.

    Parameters:
    - game_id: ID of the game

    Returns:
    - GameState: All details of the game
    """
    game = games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game

# ---------- LEADERBOARD ----------

# PUBLIC_INTERFACE
@app.get("/leaderboard", response_model=LeaderboardResponse, tags=["leaderboard"], summary="Retrieve leaderboard")
def get_leaderboard():
    """
    Returns the global leaderboard showing nickname, games played and games won.

    Returns:
    - LeaderboardResponse: List of entries sorted by most wins, then games played.
    """
    entries = list(leaderboard_stats.values())
    sorted_entries = sorted(entries, key=lambda e: (-e.games_won, -e.games_played, e.nickname.lower()))
    return LeaderboardResponse(leaderboard=sorted_entries)
