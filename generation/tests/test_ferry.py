from collections import Counter
from pathlib import Path
import tempfile
import unittest

from population.demand import PURPOSES, daily_allocations, daily_journey_rows
from population.ferry import allocate_volumes, ferry_volumes, load_scenario
from population.generate import read_csv, write_staging, make_manifest
from population.names import NameGenerator
from test_population_generation import xlsx, source_fixture
from population.generate import census_profiles, EconomicDonors

ROOT = Path(__file__).resolve().parents[1]


class FerryTests(unittest.TestCase):
    def test_route_aggregation_and_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ferry.xlsx'
            # Reuse the tiny fixture with the expected sheet name.
            xlsx(path, [['month', 'atoll', 'route_id', 'passengers'], ['2025-12', 'Haa Alifu', 'a', 3], ['2025-12', 'Haa Alifu', 'b', 4]])
            import zipfile
            with zipfile.ZipFile(path) as source:
                files = {name: source.read(name) for name in source.namelist()}
            files['xl/workbook.xml'] = files['xl/workbook.xml'].replace(b'island_code', b'ferry_monthly')
            with zipfile.ZipFile(path, 'w') as output:
                for name, value in files.items():
                    output.writestr(name, value)
            self.assertEqual(ferry_volumes(path, '2025-12'), {'Haa Alifu': 7})
            with self.assertRaisesRegex(ValueError, 'No ferry data'):
                ferry_volumes(path, '2026-01')

    def test_combined_atolls_allocate_exactly_and_uncovered_are_absent(self):
        islands = {'1': {'atoll_code': 'GA'}, '2': {'atoll_code': 'GDh'}, '3': {'atoll_code': 'K'}}
        self.assertEqual(allocate_volumes({'Gaafu Alifu & Gaafu Dhaalu': 7}, islands, {'1': 1, '2': 2, '3': 100}), {'1': 2, '2': 5})

    def test_generated_requests_export_and_filter_reproducibly(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            paths = source_fixture(folder)
            profiles = census_profiles(paths)
            donors = EconomicDonors(paths)
            names = NameGenerator(42)
            manifest = make_manifest('test', 42, names)
            manifest['data_classification'] = 'demo'
            scenario = {'month': '2025-12', 'purpose': 'other', 'appointment_time': '09:00', 'return_home_by': '18:00', 'activity_duration_minutes': 60, 'destinations': {'K': 'test-facility'}}
            counts = {'69': 8, '745': 2}
            report, preview = write_staging(folder / 'full', profiles, donors, 42, manifest, ROOT / 'schemas', names, scenario, counts)
            self.assertEqual(report['counts']['journey_requests'], 10)
            self.assertEqual(len(preview['journey_requests']), 10)
            requests = list(read_csv(folder / 'full/journey_requests.csv'))
            self.assertEqual(Counter(row['origin_island_id'] for row in requests), counts)
            self.assertTrue(all(row['data_classification'] == 'demo' for row in requests))
            write_staging(folder / 'subset', census_profiles(paths, {'69'}), donors, 42, manifest, ROOT / 'schemas', names, scenario, counts)
            self.assertEqual([row for row in requests if row['origin_island_id'] == '69'], list(read_csv(folder / 'subset/journey_requests.csv')))
            from population.generate import dump_json
            from population.export import export_run
            dump_json(folder / 'full/manifest.json', manifest)
            dump_json(folder / 'full/preview.json', preview)
            dump_json(folder / 'full/generation_report.json', report)
            try:
                import duckdb
            except ImportError:
                return
            output = export_run(folder / 'full', folder / 'export')
            with duckdb.connect() as connection:
                self.assertEqual(connection.execute('SELECT count(*) FROM read_parquet(?)', [str(output / 'journey_requests.parquet')]).fetchone()[0], 10)

    def test_scenario_requires_explicit_assumptions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scenario.json'
            path.write_text('{"month":"2025-12"}')
            with self.assertRaisesRegex(ValueError, 'exactly'):
                load_scenario(path)

    def test_daily_scenario_needs_only_month_and_times(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scenario.json'
            path.write_text('''{
              "month":"2025-12", "appointment_time":"09:00",
              "activity_duration_minutes":60, "return_home_by":"18:00"
            }''')
            scenario = load_scenario(path, 'population_daily')
            self.assertEqual(scenario['model'], 'population_daily')
            self.assertNotIn('destinations', scenario)

    def test_three_percent_daily_demand_has_random_purposes_and_health_types(self):
        self.assertEqual(sum(daily_allocations({'1': 448_819}).values()), 13_465)
        scenario = {
            'month': '2025-12', 'appointment_time': '09:00',
            'return_home_by': '18:00', 'activity_duration_minutes': 60,
        }
        people = [f'person-{index}' for index in range(100)]
        first = list(daily_journey_rows('1', people, 100, scenario, 42))
        second = list(daily_journey_rows('1', people, 100, scenario, 42))
        self.assertEqual(first, second)
        self.assertEqual(set(row['purpose'] for row in first), set(PURPOSES))
        health = [row for row in first if row['purpose'] == 'healthcare']
        self.assertEqual(set(row['destination_facility_type'] for row in health), {'hospital', 'health_centre', 'clinic'})
        self.assertTrue(all(row['destination_facility_id'] is None for row in health))
        self.assertTrue(all(row['destination_facility_id'] is None for row in first))
        self.assertEqual({row['destination_facility_type'] for row in first if row['purpose'] == 'education'}, {'government_school'})
        self.assertEqual({row['destination_facility_type'] for row in first if row['purpose'] == 'employment'}, {'workplace'})
        self.assertEqual({row['destination_facility_type'] for row in first if row['purpose'] == 'other'}, {'other'})
        first_day = [row['person_id'] for row in first if row['date'] == '2025-12-01']
        self.assertEqual(len(first_day), len(set(first_day)))

    def test_daily_demand_passes_staging_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            paths = source_fixture(folder)
            profiles = census_profiles(paths)
            names = NameGenerator(42)
            manifest = make_manifest('daily-test', 42, names)
            scenario = {
                'model': 'population_daily', 'month': '2025-12',
                'appointment_time': '09:00', 'return_home_by': '18:00',
                'activity_duration_minutes': 60,
            }
            report, preview = write_staging(
                folder / 'daily', profiles, EconomicDonors(paths), 42, manifest,
                ROOT / 'schemas', names, scenario, {'69': 1, '745': 1},
            )
            self.assertEqual(report['counts']['journey_requests'], 62)
            self.assertEqual(sum(report['journey_purpose_counts'].values()), 62)
            self.assertEqual(sum(report['destination_facility_type_counts'].values()), 62)
            self.assertTrue(preview['journey_requests'])
            requests = list(read_csv(folder / 'daily/journey_requests.csv'))
            self.assertTrue(any(row['purpose'] == 'employment' for row in requests))
            self.assertTrue(any(row['destination_facility_type'] != '\\N' for row in requests))
            from population.generate import dump_json
            from population.export import export_run
            dump_json(folder / 'daily/manifest.json', manifest)
            dump_json(folder / 'daily/preview.json', preview)
            dump_json(folder / 'daily/generation_report.json', report)
            try:
                import duckdb
            except ImportError:
                return
            output = export_run(folder / 'daily', folder / 'daily-export')
            with duckdb.connect() as connection:
                self.assertEqual(connection.execute('SELECT count(*) FROM read_parquet(?)', [str(output / 'journey_requests.parquet')]).fetchone()[0], 62)
