from dataclasses import dataclass
from typing import Optional, Dict

@dataclass
class PhoneSpec:
    slug: str                # "samsung-galaxy-s24"
    Brand: str
    Model: str
    ReleaseYear: Optional[int] = None
    OS: Optional[str] = None
    DisplayInches: Optional[float] = None
    Battery_mAh: Optional[int] = None
    RAM_GB: Optional[float] = None
    Storage_GB: Optional[float] = None
    MainCameraMP: Optional[float] = None
    Weight_g: Optional[float] = None
    NotableFeatures: Optional[str] = None
    SourceFiles: Optional[str] = None  # comma-joined raw files that produced this record

@dataclass
class PhoneOffer:
    slug: str
    retailer: str            # "bestbuy", "ebay", "amazon"
    title: str
    price: Optional[float]
    currency: str            # "USD", "PLN", ...
    url: str
    image: Optional[str] = None
    in_stock: Optional[bool] = None
    condition: Optional[str] = None  # "new", "used", "open-box"
    seen_at: str = ""                # ISO timestamp
    raw: Optional[Dict] = None       # attach trimmed raw if useful