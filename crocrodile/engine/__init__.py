# -*- coding: utf-8 -*-
"""
MyEngine Engine base.

Base engine
"""
from __future__ import print_function

import copy
import math
import random
import sys
import time
from typing import Optional

import chess
import chess.polyglot
import crocrodile.engine.evaluate as evaluation
import crocrodile.nn as nn
import requests

PAWN_VALUE = 130
KNIGHT_VALUE = 290
BISHOP_VALUE = 310
ROOK_VALUE = 500
QUEEN_VALUE = 901
KING_VALUE = 3000 # Infinity is too complex
BISHOPS_PAIR = 50
PROTECTED_KING = 5
PIECES_VALUES = {
    "p": PAWN_VALUE,
    "n": KNIGHT_VALUE,
    "b": BISHOP_VALUE,
    "r": ROOK_VALUE,
    "q": QUEEN_VALUE,
    "k": KING_VALUE,
}
CENTRAL_SQUARES = [36, 35, 28, 27]
ELARGED_SQUARES = [45, 44, 43, 42, 37, 34, 29, 26, 21, 20, 19, 18]
SEVENTH_ROW = [55, 54, 53, 52, 51, 50, 49, 48]
EIGHT_ROW = [56, 57, 58, 59, 60, 61, 62, 63]
SECOND_ROW = [15, 14, 13, 12, 11, 10, 9, 8]
FIRST_ROW = [0, 1, 2, 3, 4, 5, 6, 7]
VARIANTS = ["standard", "chess960"]


def printi(*args):
    """Debug mode printer."""
    print("info string", args)


class EngineBase:
    """Engine base."""

    def __init__(self, name, author, board=chess.Board()):
        """Initialise engine."""
        self.name = name
        self.author = author
        self.board = board
        self.tb: dict = {}
        self.tb_limit = 10000000
        self.nn_tb = dict()
        self.nn_tb_limit = 4096
        self.nn = nn.NeuralNetwork()
        self.nn.load_layers(0)
        self.evaluator = evaluation.Evaluator()
        self.nn.load_layers(0)
        self.nodes = 0
        self.depth = None
        self.opening_book = chess.polyglot.open_reader("./book.bin")
        self.obhits: int = 0
        self.tbhits: int = 0
        self.hashlimit: int = 16  # Megabytes
        self.use_nn: bool = True  # Used to disable NN
        self.hashfull: int = 0  # info hashfull

    def evaluate(self, board):
        """Evaluate position."""
        return self.evaluator.evaluate(board)

    def search(self, board, depth, maximize_white, limit_time):
        """Search best move (Minimax from wikipedia)."""
        self.nodes = 0
        self.obhits: int = 0
        self.tbhits: int = 0
        self.hashfull: int = 0
        start_time: float = time.time()
        eval, move = self.minimax_nn(board, depth, maximize_white, limit_time)
        calc_time: float = time.time() - start_time
        if eval != float("inf"):
            print(
                f"info depth {depth} nodes {self.nodes} score cp {eval} pv {move} tbhits {self.tbhits} time {int(calc_time * 1000)} nps {int(self.nodes / calc_time)} hashfull {self.hashfull} string obhits:{self.obhits}"
            )
        return eval, move

    def minimax_std(self, board, depth, maximimize_white, limit_time):
        """Minimax algorithm from Wikipedia with NN."""
        if depth == 0 or board.is_game_over():
            zobrist_hash = chess.polyglot.zobrist_hash(board)
            if zobrist_hash not in self.tb:
                # if j'ai du temps
                self.tb[zobrist_hash] = self.evaluate(board)
                if len(self.tb) > self.tb_limit:
                    del self.tb[list(self.tb.keys())[0]]
                # else
                #
            evaluation = self.tb[zobrist_hash]
            # evaluation = self.evaluate(board)
            attackers = board.attackers(board.turn, board.peek().to_square)
            if len(attackers) > 0:
                # Quiescent
                if board.turn == chess.WHITE:
                    evaluation += PIECES_VALUES[
                        board.piece_map()[board.peek().to_square].symbol().lower()
                    ]
                else:
                    evaluation -= PIECES_VALUES[
                        board.piece_map()[board.peek().to_square].symbol().lower()
                    ]
            return evaluation, chess.Move.from_uci("0000")
        if maximimize_white:
            value = -float("inf")
            legal_moves = list(board.legal_moves)
            list_best_moves = [legal_moves[0]]
            for move in legal_moves:
                if time.time() > limit_time:
                    return float("inf"), chess.Move.from_uci("0000")
                test_board = chess.Board(fen=board.fen())
                test_board.push(move)
                evaluation = self.minimax_std(test_board, depth - 1, False, limit_time)[
                    0
                ]
                if value == evaluation:
                    list_best_moves.append(move)
                elif value < evaluation:
                    value = evaluation
                    list_best_moves = [move]
            return value, random.choice(list_best_moves)
        else:
            # minimizing white
            value = float("inf")
            legal_moves = list(board.legal_moves)
            list_best_moves = [legal_moves[0]]
            for move in legal_moves:
                if time.time() > limit_time:
                    return float("inf"), chess.Move.from_uci("0000")
                test_board = chess.Board(fen=board.fen())
                test_board.push(move)
                evaluation = self.minimax_std(test_board, depth - 1, True, limit_time)[
                    0
                ]
                if value == evaluation:
                    list_best_moves.append(move)
                elif value > evaluation:
                    value = evaluation
                    list_best_moves = [move]
            return value, random.choice(list_best_moves)

    def nn_select_best_moves(self, board: chess.Board):
        """Select best moves in board."""
        hash = chess.polyglot.zobrist_hash(board)
        if hash not in self.nn_tb:
            if self.use_nn:
                good_moves = list()
                for move in board.legal_moves:
                    if self.nn.check_move(board.fen(), move.uci()):
                        good_moves.append(move)
            else:
                good_moves: list[chess.Move] = list(board.legal_moves)
            self.nn_tb[hash] = good_moves
        good_moves = self.nn_tb[hash]
        if not good_moves:
            good_moves = list(board.legal_moves)
        if int(sys.getsizeof(self.nn_tb) / 1024 / 1024) >= self.hashlimit / 2:
            del self.nn_tb[list(self.nn_tb.keys())[0]]
            self.hashfull += 1
        return good_moves

    def get_book_move(self, board: chess.Board) -> Optional[chess.Move]:
        """Get move from opening book.

        :param board: Board to get move.
        :type board: chess.Board
        :return: A random move from the opening book?
        :rtype: Optional[chess.Move]
        """
        try:
            return self.opening_book.weighted_choice(board).move
        except IndexError:
            return False

    # + param time + param best move depth-1 + param evaluation
    def minimax_nn(self, board: chess.Board, depth, maximimize_white, limit_time):
        """Minimax algorithm from Wikipedia with NN."""
        self.nodes += 1
        if depth == 0 or board.is_game_over():
            evaluation = self.evaluate(board)
            # evaluation = self.evaluate(board)
            """attackers = board.attackers(board.turn, board.peek().to_square)
            if len(attackers) > 0:
                # Quiescent
                if board.turn == chess.WHITE:
                    evaluation += PIECES_VALUES[board.piece_map()
                                                [board.peek().to_square].
                                                symbol().lower()]
                else:
                    evaluation -= PIECES_VALUES[board.piece_map()
                                                [board.peek().to_square].
                                                symbol().lower()]"""
            return evaluation, chess.Move.from_uci("0000")
        if maximimize_white:
            book_move = None
            if board.fullmove_number < 15 and (book_move := self.get_book_move(board)):
                self.obhits += 1
                return 10000, book_move
            if len(board.piece_map()) <= 7:
                formatted_fen = board.fen().replace(" ", "_")
                data = requests.get(
                    f"http://tablebase.lichess.ovh/standard?fen={formatted_fen}"
                ).json()
                good_move = chess.Move.from_uci(data["moves"][0]["uci"])
                if data["category"] in ("win", "maybe_win", "cursed-win"):
                    self.tbhits += 1
                    return 10000, good_move
                elif data["category"] in ("loss", "maybe-loss", "blessed-loss"):
                    self.tbhits += 1
                    return -10000, good_move
                elif data["category"] == "draw":
                    self.tbhits += 1
                    return 0, good_move
                else:
                    pass
            value = -float("inf")
            legal_moves = list(board.legal_moves)
            list_best_moves = [legal_moves[0]]
            for move in self.nn_select_best_moves(board):
                if time.time() > limit_time:
                    return float("inf"), chess.Move.from_uci("0000")
                test_board = chess.Board(fen=board.fen())
                test_board.push(move)
                hash = chess.polyglot.zobrist_hash(test_board)
                if hash in self.tb and self.tb[hash][0] >= (depth - 1):
                    evaluation: int = self.tb[hash][1]
                else:
                    evaluation = self.minimax_nn(
                        test_board, depth - 1, False, limit_time
                    )[0]
                    self.tb[hash] = (copy.copy(depth), copy.copy(evaluation))
                    if int(sys.getsizeof(self.tb) / 1024 / 1024) >= self.hashlimit / 2:
                        del self.tb[list(self.tb.keys())[0]]
                        self.hashfull += 1
                if value == evaluation:
                    list_best_moves.append(move)
                elif value < evaluation:
                    value = evaluation
                    list_best_moves = [move]
            return value, random.choice(list_best_moves)
        else:
            book_move = None
            if board.fullmove_number < 15 and (book_move := self.get_book_move(board)):
                self.obhits += 1
                return -10000, book_move
            if len(board.piece_map()) <= 7:
                formatted_fen = board.fen().replace(" ", "_")
                data = requests.get(
                    f"http://tablebase.lichess.ovh/standard?fen={formatted_fen}"
                ).json()
                good_move = chess.Move.from_uci(data["moves"][0]["uci"])
                if data["category"] in ("win", "maybe_win", "cursed-win"):
                    self.tbhits += 1
                    return -10000, good_move
                elif data["category"] in ("loss", "maybe-loss", "blessed-loss"):
                    self.tbhits += 1
                    return 10000, good_move
                elif data["category"] == "draw":
                    self.tbhits += 1
                    return 0, good_move
                else:
                    pass
            # minimizing white
            value = float("inf")
            legal_moves = list(board.legal_moves)
            list_best_moves = [legal_moves[0]]
            for move in self.nn_select_best_moves(board):
                if time.time() > limit_time:
                    return float("inf"), chess.Move.from_uci("0000")
                test_board = chess.Board(fen=board.fen())
                test_board.push(move)
                hash = chess.polyglot.zobrist_hash(test_board)
                if hash in self.tb and self.tb[hash][0] >= (depth - 1):
                    evaluation: int = self.tb[hash][1]
                else:
                    evaluation = self.minimax_nn(
                        test_board, depth - 1, True, limit_time
                    )[0]
                    self.tb[hash] = (copy.copy(depth), copy.copy(evaluation))
                    if int(sys.getsizeof(self.tb) / 1024 / 1024) >= self.hashlimit / 2:
                        del self.tb[list(self.tb.keys())[0]]
                        self.hashfull += 1
                if value == evaluation:
                    list_best_moves.append(move)
                elif value > evaluation:
                    value = evaluation
                    list_best_moves = [move]
            return value, random.choice(list_best_moves)
