"""
Load CLEARLY LABELLED sample data for local testing of the campus features.

    python -m backend.seed_sample_data            # add sample data
    python -m backend.seed_sample_data --remove   # delete it again

Every sample team name starts with "[SAMPLE]", every sample user id starts
with "sample_", and both are stored with is_sample = 1 so that the API
returns "is_sample": true. This is NOT real student participation.
"""

import sys
from datetime import datetime, timedelta, timezone

from .app import create_app
from .database import connect, get_db_path
from .errors import ConflictError, ValidationError
from .services import campus_service, footprint_service

# (team, [(user, [weekly quantities per saved record, oldest first])])
SAMPLE = [
    ("[SAMPLE] Green Warriors", [
        ("sample_aarav", [
            {"bottle": 7, "bag": 5, "straw": 3, "cutlery": 2, "box": 2,
             "cup": 4, "wrap": 6},
            {"bottle": 3, "bag": 2, "straw": 0, "cutlery": 1, "box": 1,
             "cup": 2, "wrap": 5}]),
        ("sample_meera", [
            {"bottle": 5, "bag": 3, "straw": 2, "cutlery": 1, "box": 3,
             "cup": 5, "wrap": 4},
            {"bottle": 4, "bag": 3, "straw": 1, "cutlery": 1, "box": 2,
             "cup": 4, "wrap": 4}]),
    ]),
    ("[SAMPLE] Eco Rangers", [
        ("sample_kabir", [
            {"bottle": 10, "bag": 6, "straw": 4, "cutlery": 3, "box": 4,
             "cup": 6, "wrap": 8},
            {"bottle": 9, "bag": 6, "straw": 4, "cutlery": 3, "box": 3,
             "cup": 6, "wrap": 8}]),
        ("sample_zoya", [
            {"bottle": 2, "bag": 1, "straw": 0, "cutlery": 0, "box": 1,
             "cup": 1, "wrap": 3}]),
    ]),
]


def remove(conn):
    conn.execute("DELETE FROM users WHERE is_sample = 1")  # cascades
    conn.execute("DELETE FROM teams WHERE is_sample = 1")
    conn.commit()


def seed():
    app = create_app()
    conn = connect(get_db_path(app))
    try:
        remove(conn)  # make the script safe to run more than once
        start = datetime.now(timezone.utc) - timedelta(weeks=4)
        for team_name, members in SAMPLE:
            team = campus_service.create_team(
                conn, team_name, "Sample team for local testing only.",
                is_sample=True)
            for user_id, weeks in members:
                campus_service.join_team(conn, user_id, team["id"],
                                         display_name="Sample student",
                                         is_sample=True)
                for index, quantities in enumerate(weeks):
                    when = start + timedelta(weeks=2 * index)
                    footprint_service.save_calculation(
                        conn, user_id, quantities,
                        recorded_at=when.isoformat(timespec="seconds"),
                        sample=True)
        print("Sample data loaded into", get_db_path(app))
        print("Every sample record is flagged is_sample = true.")
    except (ConflictError, ValidationError) as exc:
        # e.g. a REAL user or team already uses a sample id/name (possible
        # only in databases created before those names were reserved).
        conn.rollback()
        remove(conn)
        print("Sample data NOT loaded:", exc.message)
        print("Real data was not changed.")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    if "--remove" in sys.argv:
        app = create_app()
        c = connect(get_db_path(app))
        remove(c)
        c.close()
        print("Sample data removed.")
    else:
        seed()
