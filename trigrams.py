#!/usr/bin/env python3

"""
  Inspiration:

    https://twitter.com/schrepfler/status/1512434401652654085?s=20&t=JwOC6W-CXvPVIFu-ua9Iyw
    https://www.postgresql.org/docs/current/pgtrgm.html

  Data:
  
    https://en.wikipedia.org/wiki/List_of_professional_sports_teams_in_the_United_States_and_Canada

  PR which enables GIN index acceleration for the ARRAY && ARRAY operation:

    https://github.com/cockroachdb/cockroach/pull/77418

  DDL:

    DROP TABLE IF EXISTS teams CASCADE;
    CREATE TABLE teams
    (
      id UUID PRIMARY KEY DEFAULT GEN_RANDOM_UUID()
      , name TEXT NOT NULL
      , grams TEXT[]
      , FAMILY f1 (id, name)
      , FAMILY f2 (grams)
    );
    CREATE INDEX ON teams USING GIN (grams);

  CDC to webhook endpoint (this Python script):

    CREATE CHANGEFEED FOR TABLE teams family "f1"
    INTO 'webhook-https://localhost:18080/cdc?insecure_tls_skip_verify=true'
    WITH updated, full_table_name, topic_in_value;

"""

import os, sys, re
import psycopg2, psycopg2.errorcodes
import logging
import time
import random

from sqlalchemy import create_engine, text
import sqlalchemy

# For Web app
from flask import Flask, request, Response
import json
import base64

# $Id: trigrams.py,v 1.10 2022/04/09 19:19:10 mgoddard Exp mgoddard $

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%m/%d/%Y %I:%M:%S %p")

conn_str = os.getenv("DB_CONN_STR")
if conn_str is None:
  print("Env. var. 'DB_CONN_STR' must be set")
  sys.exit(1)

# Maximum number of query retries (to the DB)
max_retries = int(os.getenv("MAX_RETRIES", "4"))
logging.info("MAX_RETRIES: {}".format(max_retries))

# SQLAlchemy has a CockroachDB dialect
conn_str = re.sub(r"^postgres[^:]*", "cockroachdb", conn_str)
logging.info("DB_CONN_STR (rewritten): {}".format(conn_str))

# Delta t in seconds for follower reads
aost_seconds = os.getenv("AOST_SECONDS", "10")
logging.info("AOST_SECONDS: {}".format(aost_seconds))

# Init Flask app
app = Flask(__name__)

# SQLAlchemy engine instance
engine = create_engine(conn_str, pool_pre_ping=True)
logging.info("Engine: OK")

# Run the given SQL statement; if has_result is True, returns result set
def run_statement(stmt, has_result=False, use_aost=False):
  for retry in range(1, max_retries + 1):
    rv = None
    try:
      if use_aost: # Use follower reads
        with engine.begin() as conn:
          aost = text("SET TRANSACTION AS OF SYSTEM TIME :dt").bindparams(dt='-' + aost_seconds + 's')
          conn.execute(aost)
          result = conn.execute(stmt)
          rv = result.all()
      elif has_result: # This was a SELECT
        with engine.connect() as conn:
          result = conn.execute(stmt)
          rv = result.all()
      else: # INSERT, UPSERT, DDL, ...
        with engine.begin() as conn:
          conn.execute(stmt)
      return rv
    except sqlalchemy.exc.OperationalError as e:
      logging.warning(e)
      # Check the underlying error in e.orig
      logging.warning(e.orig)
      if e.orig.pgcode == psycopg2.errorcodes.SERIALIZATION_FAILURE:
        sleep_s = (2 ** retry) * 0.1 * (random.random() + 0.5)
        logging.warning("RETRY (40001): sleeping {} seconds".format(sleep_s))
        time.sleep(sleep_s)
      else:
        logging.warning("OperationalError: sleeping 5 seconds")
        time.sleep(5)
    except (sqlalchemy.exc.IntegrityError, psycopg2.errors.UniqueViolation) as e:
      logging.warning(e)
      logging.warning("UniqueViolation: continuing to next TXN")
    except psycopg2.Error as e:
      logging.warning(e)
      logging.warning("Not sure about this one ... sleeping 5 seconds, though")
      time.sleep(5)

def get_ngrams(s, n=3):
  return list(set([s[i:i+n] for i in range(len(s) - n+1)]))

def tokenize(s):
  rv = []
  for t in get_ngrams(re.sub(r"[\W_]+", " ", s.lower())):
    rv.append(t)
  return rv

def index_string(pk, content):
  ng = tokenize(content)
  stmt = text("UPDATE teams SET grams = :grams WHERE id = :pk").bindparams(grams=ng, pk=pk)
  run_statement(stmt)

# Decode a base64 encoded value to a UTF-8 string
CHARSET = "utf-8"
def decode(b64):
  b = base64.b64decode(b64)
  return b.decode(CHARSET).strip()

#
# Search/query endpoint (shown here with a limit of 5 results):
#
#   time curl http://localhost:18080/search/$( echo -n "Using Lateral Joins" | base64 )/5
#
@app.route("/search/<q_base_64>/<int:limit>")
def do_search(q_base_64, limit):
  query_str = decode(q_base_64)
  logging.info("Query: {}".format(query_str))
  ng = tokenize(query_str)
  logging.info("Query (n-grams): {}".format(ng))
  sql = """
  WITH qbool AS
  (
    SELECT id, grams, 1 + ABS(ARRAY_LENGTH(grams, 1) - ARRAY_LENGTH(CAST(:ngrams AS TEXT[]), 1)) delta
    FROM teams
    WHERE grams && CAST(:ngrams AS TEXT[])
  ), qscore AS
  (
    SELECT id, COUNT(*) n FROM
    (
      SELECT id, UNNEST(grams) FROM qbool
      INTERSECT
      SELECT id, UNNEST(CAST(:ngrams AS TEXT[])) FROM qbool
    )
    GROUP BY id
  )
  SELECT qbool.id, t.name, 100*n/delta score
  FROM qbool, qscore, teams t
  WHERE qbool.id = qscore.id AND t.id = qbool.id
  ORDER BY score DESC
  LIMIT :max_rows;
  """
  stmt = text(sql).bindparams(ngrams=ng, max_rows=limit)
  rv = []
  for row in run_statement(stmt, True, False):
    pk = str(row[0])
    name = str(row[1])
    score = float(row[2]/len(ng))
    d = {}
    (d["pk"], d["name"], d["score"]) = (pk, name, '{:.4f}'.format(score))
    rv.append(d)
  return Response(json.dumps(rv), status=200, mimetype="application/json")

@app.route('/cdc', methods = ['POST', 'GET'])
def cdc_webhook():
  obj = request.get_json(force=True)
  print("CDC: " + json.dumps(obj)) # DEBUG
  for o in obj["payload"]:
    if o["after"] is None:
      pass # Nothing to be done here
    else:
      pk = o["after"]["id"]
      name = o["after"]["name"]
      index_string(pk, name)
  return "OK", 200

if __name__ == '__main__':
  port = int(os.getenv("FLASK_PORT", 18080))
  # Start the Flask app
  app.run(ssl_context='adhoc', host='0.0.0.0', port=port, threaded=True, debug=False)

