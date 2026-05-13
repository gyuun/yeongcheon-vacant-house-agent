from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import VacantHouseRecord


class PublicDataClient(ABC):
    """Boundary for Yeongcheon/open public-data APIs."""

    @abstractmethod
    def get_vacant_house(self, house_id: str) -> VacantHouseRecord:
        """Fetch one vacant-house record."""


class MockPublicDataClient(PublicDataClient):
    """Deterministic stand-in until the target public-data APIs are selected."""

    def get_vacant_house(self, house_id: str) -> VacantHouseRecord:
        fixtures = {
            "YC-001": VacantHouseRecord(
                house_id="YC-001",
                address="경상북도 영천시 중앙동",
                building_age_years=42,
                vacancy_years=6,
                structure_grade="D",
                complaints_last_year=8,
                distance_to_road_m=12.0,
                distance_to_public_facility_m=280.0,
                land_area_m2=142.5,
                latitude=35.9682723,
                longitude=128.931526,
                metadata={"source": "mock"},
            ),
            "YC-002": VacantHouseRecord(
                house_id="YC-002",
                address="경상북도 영천시 완산동",
                building_age_years=24,
                vacancy_years=2,
                structure_grade="B",
                complaints_last_year=1,
                distance_to_road_m=38.0,
                distance_to_public_facility_m=90.0,
                land_area_m2=84.0,
                latitude=35.9614,
                longitude=128.9381,
                metadata={"source": "mock"},
            ),
        }

        return fixtures.get(
            house_id,
            VacantHouseRecord(
                house_id=house_id,
                address="경상북도 영천시",
                building_age_years=35,
                vacancy_years=4,
                structure_grade="C",
                complaints_last_year=3,
                distance_to_road_m=30.0,
                distance_to_public_facility_m=180.0,
                land_area_m2=100.0,
                metadata={"source": "mock-default"},
            ),
        )
