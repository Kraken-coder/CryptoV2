import numpy as np
from env import (
    band1_lower, band1_upper, leverage_band1,
    band2_lower, band2_upper, leverage_band2,
    band3_lower, band3_upper, leverage_band3,
    band4_lower, leverage_band4
)

class TradingPrice:
    def __init__(self):
        # Corrected list syntax
        self.prob = ['Flat', 'Large Down', 'Large Up', 'Medium Down', 'Medium Up']
        self.weights = np.array([0 ,  -2 , 2 , -1 , 1])

    def calculate_edge(self, probs):
        # Handle sklearn predict_proba output which is (1, n_classes)
        if hasattr(probs, 'ndim') and probs.ndim > 1:
            probs = probs.flatten()
        edge = np.dot(self.weights, probs)
        return edge

    def get_trade_decision(self, edge):
        """
        Returns (side, leverage, description) based on new 4-band system
        """
        abs_edge = abs(edge)
        
        # Determine Band
        band = 0
        leverage = 0
        desc = "No Trade"

        if abs_edge >= band4_lower:
            band = 4
            leverage = leverage_band4
            desc = "Band 4 (Extreme)"
        elif band3_lower <= abs_edge < band3_upper:
            band = 3
            leverage = leverage_band3
            desc = "Band 3 (Strong)"
        elif band2_lower <= abs_edge < band2_upper:
            band = 2
            leverage = leverage_band2
            desc = "Band 2 (Medium)"
        elif band1_lower <= abs_edge < band1_upper:
            band = 1
            leverage = leverage_band1
            desc = "Band 1 (Weak)"
        
        if band == 0:
            return "NEUTRAL", 0, "No Trade"
        
        side = "BUY" if edge > 0 else "SELL"
        return side, leverage, desc