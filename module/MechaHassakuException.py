
# -*- coding: utf-8 -*-
"""
Created on Sun Feb 25 20:42:17 2024

@author: seesthenight & Circle D5
"""

class MechaHassakuError(Exception):
    def __init__(self, message, file):
        self.message = message
        self.file = file
        super().__init__(message)