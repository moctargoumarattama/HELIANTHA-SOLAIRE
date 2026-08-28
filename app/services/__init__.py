"""Services metier de la phase 3.

Ces services restent independants de Flask et de SQLite. Ils travaillent avec
des dictionnaires produit afin de pouvoir etre utilises aussi bien par le
moteur, les tests que par un futur import catalogue.
"""

from .bom_builder import BOMBuilder
from .compatibility import CompatibilityChecker
from .pricing import PricingEngine
from .product_selector import ProductSelector

__all__ = ["BOMBuilder", "CompatibilityChecker", "PricingEngine", "ProductSelector"]
