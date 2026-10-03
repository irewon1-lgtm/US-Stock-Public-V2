import contextlib
import copy
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('refresh', ROOT / 'scripts/refresh-batch.py')
refresh = importlib.util.module_from_spec(spec); spec.loader.exec_module(refresh)
spec_csv = importlib.util.spec_from_file_location('csv_builder', ROOT / 'scripts/build-analysis-csv.py')
csv_builder = importlib.util.module_from_spec(spec_csv); spec_csv.loader.exec_module(csv_builder)
CONFIG = json.loads((ROOT / 'config/metrics-v2.json').read_text())
SOURCES = {m['key']:m['source'] for m in CONFIG['metrics']}
DAY = '2026-10-03'
OLD = '2026-09-28T00:00:00Z'
NOW = DAY+'T01:00:00Z'
FCF = 'FCF_Yield_TTM_Pct'
GROSS = 'Gross_Margin_TTM_Pct'

def row(ticker='TEST', numeric=8):
    metrics = {k:{'value':1.0,'status':'NUMERIC','source':SOURCES[k],'updatedAt':OLD} for k in refresh.METRIC_KEYS}
    if numeric == 8: metrics[GROSS].update(status='NA_BASIS',value=None)
    return {'ticker':ticker,'company':'Previous verified company','sector':'Financial','metrics':metrics,'numericCount':numeric,'resolvedCount':9,'lastAttemptAt':None,'lastSuccessfulRefreshAt':OLD}

def fresh(statuses, errors=None):
    return {'company':'Candidate company','metrics':{k:{'value':2.0 if v=='NUMERIC' else None,'status':v,'asOf':DAY,'reason':'Fixture source observation','sourceUrls':['https://example.test/source']} for k,v in statuses.items()},'collectionErrors':errors or []}

def merge(before, candidate, at=NOW):
    return refresh.merge_refresh(before,candidate,DAY,at,SOURCES)

class HoldTests(unittest.TestCase):
    def test_regression_holds_entire_previous_record_and_timestamps(self):
        old=row(); before=copy.deepcopy(old)
        new=merge(old,fresh({FCF:'NA_BASIS','ROA_TTM_Pct':'NUMERIC'}))
        self.assertEqual(old,before)
        self.assertEqual(new['metrics'],old['metrics'])
        self.assertEqual(new['company'],old['company'])
        self.assertEqual(new['lastSuccessfulRefreshAt'],OLD)
        self.assertEqual(new['lastAttemptAt'],NOW)
        self.assertEqual(new['numericCount'],8)
        self.assertEqual(new['refreshHold']['candidateNumericCount'],7)
        self.assertEqual(new['refreshHold']['regressedMetrics'][0]['observedStatus'],'NA_BASIS')

    def test_nine_to_seven_holds_both_regressions(self):
        old=row(numeric=9); new=merge(old,fresh({FCF:'NA_BASIS',GROSS:'NA_BASIS'}))
        self.assertEqual(new['numericCount'],9)
        self.assertEqual({r['key'] for r in new['refreshHold']['regressedMetrics']},{FCF,GROSS})

    def test_valid_eight_of_nine_is_accepted(self):
        new=merge(row(numeric=9),fresh({FCF:'NA_BASIS'}))
        self.assertNotIn('refreshHold',new)
        self.assertEqual(new['numericCount'],8)
        self.assertEqual(new['metrics'][FCF]['status'],'NA_BASIS')
        self.assertEqual(new['lastSuccessfulRefreshAt'],NOW)

    def test_failed_fetch_does_not_clear_previous_hold(self):
        held=merge(row(),fresh({FCF:'NA_BASIS'})); later=DAY+'T07:00:00Z'
        new=merge(held,fresh({'ROA_TTM_Pct':'NUMERIC'},['StockAnalysis:TIMEOUT']),later)
        self.assertEqual(new['metrics'],held['metrics'])
        self.assertEqual(new['lastSuccessfulRefreshAt'],OLD)
        self.assertEqual(new['refreshHold']['reason'],'PREVIOUS_COVERAGE_HOLD_UNRESOLVED')
        self.assertEqual(new['refreshHold']['firstHeldAt'],NOW)
        self.assertEqual(new['refreshHold']['attemptedAt'],later)
        self.assertEqual(new['refreshHold']['collectionErrors'],['StockAnalysis:TIMEOUT'])
        self.assertEqual(new['refreshHold']['regressedMetrics'][0]['observedAt'],NOW)

    def test_real_collector_cache_fallback_cannot_clear_hold(self):
        from server.public_site_fundamentals import collect_ticker, PublicSourceError
        held=merge(row(),fresh({FCF:'NA_BASIS'}))
        def failed(ticker): raise PublicSourceError('FIXTURE_ACCESS_FAILURE')
        collected=collect_ticker({'ticker':'TEST','sector':'Financial'},DAY,held,fetchers={'finviz':failed,'stockanalysis':failed})
        self.assertNotIn('asOf',collected['metrics'][FCF])
        updated=merge(held,collected)
        self.assertIn('refreshHold',updated)
        self.assertEqual(updated['metrics'],held['metrics'])

    def test_previous_day_numeric_observation_cannot_clear_hold(self):
        held=merge(row(),fresh({FCF:'NA_BASIS'}))
        candidate=fresh({FCF:'NUMERIC'})
        candidate['metrics'][FCF]['asOf']='2026-10-02'
        updated=merge(held,candidate)
        self.assertIn('refreshHold',updated)
        self.assertEqual(updated['metrics'][FCF]['updatedAt'],OLD)

    def test_repeated_na_preserves_first_hold_but_updates_attempt(self):
        held=merge(row(),fresh({FCF:'NA_BASIS'})); later=DAY+'T07:00:00Z'
        new=merge(held,fresh({FCF:'NA_BASIS'}),later)
        self.assertEqual(new['refreshHold']['firstHeldAt'],NOW)
        self.assertEqual(new['refreshHold']['attemptedAt'],later)
        self.assertEqual(new['metrics'][FCF]['updatedAt'],OLD)

    def test_recovery_clears_hold_and_updates_only_observed_cells(self):
        held=merge(row(),fresh({FCF:'NA_BASIS'})); recovered=merge(held,fresh({FCF:'NUMERIC'}))
        self.assertNotIn('refreshHold',recovered)
        self.assertEqual(recovered['metrics'][FCF]['value'],2)
        self.assertEqual(recovered['metrics'][FCF]['updatedAt'],NOW)
        self.assertEqual(recovered['metrics'][GROSS]['updatedAt'],OLD)

    def test_new_valid_na_can_be_accepted_if_another_metric_recovers(self):
        held=merge(row(),fresh({FCF:'NA_BASIS'}))
        recovered=merge(held,fresh({FCF:'NA_BASIS',GROSS:'NUMERIC'}))
        self.assertNotIn('refreshHold',recovered)
        self.assertEqual(recovered['numericCount'],8)
        self.assertIsNone(recovered['metrics'][FCF]['value'])

    def test_hold_status_does_not_relabel_metric_cells(self):
        held=merge(row(),fresh({FCF:'HOLD'}))
        self.assertNotIn('refreshHold',held)
        self.assertEqual(held['metrics'][FCF]['updatedAt'],OLD)
        self.assertEqual(set(held['metrics'][FCF]),{'value','status','source','updatedAt'})

    def fixture(self, path):
        records=[row(f'T{i:04}') for i in range(3700)]
        state={'schema':'US_PUBLIC_V2_STATE_V1','recordCount':3700,'metricCount':9,'generatedAt':OLD,'records':records}
        (path/'state.json').write_text(json.dumps(state)); (path/'universe.json').write_text(json.dumps({'recordCount':3700,'tickers':[r['ticker'] for r in records]}))
        return state

    def run_main(self, path, collector, hour=1):
        args=['refresh','--universe',str(path/'universe.json'),'--config',str(ROOT/'config/metrics-v2.json'),'--state',str(path/'state.json'),'--seed',str(path/'state.json'),'--status',str(path/'status.json'),'--count','1000','--workers','3']
        with patch.object(sys,'argv',args),patch.object(refresh,'collect_ticker',collector),patch.object(refresh,'utc_now',return_value=f'{DAY}T{hour:02}:00:00Z'),contextlib.redirect_stdout(io.StringIO()):
            refresh.main()
        return json.loads((path/'state.json').read_text()),json.loads((path/'status.json').read_text())

    def test_hold_does_not_trap_queue_and_gets_retried(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td); self.fixture(p); attempts=[]
            def collect(identity,day,previous):
                attempts.append(identity['ticker'])
                return fresh({FCF:'NA_BASIS'} if identity['ticker']=='T0000' else {FCF:'NUMERIC'})
            state,status=self.run_main(p,collect)
            self.assertEqual(status['heldRecordCount'],1)
            self.assertEqual(status['heldInBatchCount'],1)
            self.assertEqual(status['records8plusNumeric'],3700)
            self.assertEqual(status['heldRecords'][0]['ticker'],'T0000')
            for hour in (7,13,19): state,status=self.run_main(p,collect,hour)
            self.assertEqual(len(set(attempts)),3700)
            self.assertEqual(attempts.count('T0000'),2)
            self.assertEqual(state['records'][0]['lastSuccessfulRefreshAt'],OLD)
            self.assertEqual(state['records'][0]['refreshHold']['attemptedAt'],DAY+'T19:00:00Z')

    def test_final_guard_still_rejects_invalid_preexisting_row(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td); state=self.fixture(p)
            state['records'][-1]['metrics'][FCF].update(status='NA_BASIS',value=None)
            state['records'][-1]['numericCount']=7
            (p/'state.json').write_text(json.dumps(state)); before=(p/'state.json').read_bytes()
            with self.assertRaisesRegex(RuntimeError,'PUBLIC_V2_COVERAGE_BELOW_8_OF_9:3699'):
                self.run_main(p,lambda *args:fresh({}))
            self.assertEqual((p/'state.json').read_bytes(),before)
            self.assertFalse((p/'status.json').exists())

    def test_csv_marks_held_values_and_preserves_dates(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td); state=self.fixture(p); state['records'][0]=merge(state['records'][0],fresh({FCF:'NA_BASIS'}))
            (p/'state.json').write_text(json.dumps(state))
            with patch.object(sys,'argv',['csv','--state',str(p/'state.json'),'--out',str(p/'analysis.csv')]),contextlib.redirect_stdout(io.StringIO()): csv_builder.main()
            with (p/'analysis.csv').open(encoding='utf-8-sig',newline='') as f: output={r['ticker']:r for r in csv.DictReader(f)}
            held=output['T0000']; normal=output['T0001']
            self.assertEqual(held['refresh_held'],'1')
            self.assertEqual(held['data_quality_flag'],'REFRESH_HELD_PREVIOUS_VALUES')
            self.assertEqual(held['fcf_yield_updated_at'],OLD)
            self.assertEqual(held['quantitative_score'],normal['quantitative_score'])

if __name__=='__main__':unittest.main()
