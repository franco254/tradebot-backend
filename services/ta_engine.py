import pandas as pd
import pandas_ta as ta
import numpy as np


class TAEngine:
    """
    Technical Analysis Engine.
    Takes OHLCV price data and returns indicator values + trade signal.
    """

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.rsi_period      = cfg.get('rsi_period', 14)
        self.rsi_overbought  = cfg.get('rsi_overbought', 70)
        self.rsi_oversold    = cfg.get('rsi_oversold', 30)
        self.macd_fast       = cfg.get('macd_fast', 12)
        self.macd_slow       = cfg.get('macd_slow', 26)
        self.macd_signal     = cfg.get('macd_signal', 9)
        self.ema_period      = cfg.get('ema_period', 20)
        self.bb_period       = cfg.get('bb_period', 20)
        self.bb_std          = cfg.get('bb_std', 2)

    def analyze(self, df: pd.DataFrame) -> dict:
        """
        Run full TA analysis on OHLCV dataframe.
        df must have columns: open, high, low, close, volume
        Returns dict with indicators + signal (BUY/SELL/HOLD) + confidence
        """
        if df is None or len(df) < self.macd_slow + 10:
            return self._empty_result()

        df = df.copy()

        # ── Indicators ──
        df['rsi']  = ta.rsi(df['close'], length=self.rsi_period)
        macd       = ta.macd(df['close'], fast=self.macd_fast,
                             slow=self.macd_slow, signal=self.macd_signal)
        df['macd']        = macd[f'MACD_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}']
        df['macd_signal'] = macd[f'MACDs_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}']
        df['macd_hist']   = macd[f'MACDh_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}']
        df['ema']  = ta.ema(df['close'], length=self.ema_period)
        bb         = ta.bbands(df['close'], length=self.bb_period, std=self.bb_std)
        df['bb_upper'] = bb[f'BBU_{self.bb_period}_{float(self.bb_std)}']
        df['bb_lower'] = bb[f'BBL_{self.bb_period}_{float(self.bb_std)}']
        df['bb_mid']   = bb[f'BBM_{self.bb_period}_{float(self.bb_std)}']

        # Use last completed candle
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last

        rsi        = round(float(last['rsi']),  2) if not pd.isna(last['rsi'])  else 50.0
        macd_val   = round(float(last['macd']), 4) if not pd.isna(last['macd']) else 0.0
        macd_sig   = round(float(last['macd_signal']), 4) if not pd.isna(last['macd_signal']) else 0.0
        macd_hist  = round(float(last['macd_hist']), 4) if not pd.isna(last['macd_hist']) else 0.0
        ema        = round(float(last['ema']),  4) if not pd.isna(last['ema'])  else 0.0
        price      = round(float(last['close']), 4)
        bb_upper   = round(float(last['bb_upper']), 4) if not pd.isna(last['bb_upper']) else 0.0
        bb_lower   = round(float(last['bb_lower']), 4) if not pd.isna(last['bb_lower']) else 0.0
        bb_width   = round(((bb_upper - bb_lower) / price) * 100, 2) if price else 0.0

        # ── Signal Logic ──
        signal, confidence = self._generate_signal(
            rsi, macd_val, macd_sig, macd_hist,
            price, ema, bb_upper, bb_lower,
            float(prev['macd_hist']) if not pd.isna(prev['macd_hist']) else 0.0
        )

        return {
            'signal':     signal,
            'confidence': confidence,
            'price':      price,
            'indicators': {
                'rsi':       rsi,
                'macd':      macd_val,
                'macd_signal': macd_sig,
                'macd_hist': macd_hist,
                'ema':       ema,
                'bb_upper':  bb_upper,
                'bb_lower':  bb_lower,
                'bb_width':  bb_width,
            }
        }

    def _generate_signal(self, rsi, macd, macd_sig, macd_hist,
                          price, ema, bb_upper, bb_lower, prev_hist):
        """
        Multi-indicator confluence scoring system.
        Each condition adds/subtracts from a score, then maps to BUY/SELL/HOLD.
        """
        score = 0
        reasons = 0

        # RSI signals
        if rsi < self.rsi_oversold:
            score += 2; reasons += 1        # Strong oversold → BUY
        elif rsi < 45:
            score += 1; reasons += 1        # Mild bullish bias
        elif rsi > self.rsi_overbought:
            score -= 2; reasons += 1        # Strong overbought → SELL
        elif rsi > 55:
            score -= 1; reasons += 1        # Mild bearish bias

        # MACD crossover
        if macd_hist > 0 and prev_hist <= 0:
            score += 2; reasons += 1        # Bullish crossover
        elif macd_hist < 0 and prev_hist >= 0:
            score -= 2; reasons += 1        # Bearish crossover
        elif macd_hist > 0:
            score += 1; reasons += 1        # MACD positive momentum
        elif macd_hist < 0:
            score -= 1; reasons += 1        # MACD negative momentum

        # Price vs EMA
        if price > ema * 1.002:
            score += 1; reasons += 1        # Price above EMA → bullish
        elif price < ema * 0.998:
            score -= 1; reasons += 1        # Price below EMA → bearish

        # Bollinger Bands
        if bb_lower and price <= bb_lower:
            score += 1; reasons += 1        # Price at lower band → potential bounce
        elif bb_upper and price >= bb_upper:
            score -= 1; reasons += 1        # Price at upper band → potential pullback

        # Map score to signal + confidence
        max_score = reasons * 2 if reasons else 1
        confidence = min(int((abs(score) / max_score) * 100), 99)

        if score >= 2:
            return 'BUY',  max(confidence, 55)
        elif score <= -2:
            return 'SELL', max(confidence, 55)
        else:
            return 'HOLD', max(confidence, 40)

    def _empty_result(self):
        return {
            'signal': 'HOLD',
            'confidence': 0,
            'price': 0.0,
            'indicators': {
                'rsi': 50.0, 'macd': 0.0, 'macd_signal': 0.0,
                'macd_hist': 0.0, 'ema': 0.0,
                'bb_upper': 0.0, 'bb_lower': 0.0, 'bb_width': 0.0
            }
        }
