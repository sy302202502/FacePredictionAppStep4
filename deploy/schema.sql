--
-- PostgreSQL database schema (idempotent version)
-- CREATE TABLE IF NOT EXISTS / CREATE SEQUENCE IF NOT EXISTS
-- 何度実行してもエラーにならない
--

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;
SET default_tablespace = '';
SET default_table_access_method = heap;

-- ============================================================
-- SEQUENCES
-- ============================================================

CREATE SEQUENCE IF NOT EXISTS public.face_image_id_seq
    START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.grade_race_result_id_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.high_dividend_selection_id_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.horse_face_feature_id_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.prediction_accuracy_id_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.prediction_result_id_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.race_entry_id_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.race_odds_id_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.race_specific_accuracy_id_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.race_specific_prediction_id_seq
    START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.race_specific_result_id_seq
    START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.races_id_seq
    START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.stats_prediction_id_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;


-- ============================================================
-- TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS public.face_image (
    id bigint NOT NULL DEFAULT nextval('public.face_image_id_seq'::regclass),
    horse_name character varying(255),
    image_path character varying(255),
    score integer NOT NULL,
    track_condition character varying(255)
);

CREATE TABLE IF NOT EXISTS public.grade_race_result (
    id integer NOT NULL DEFAULT nextval('public.grade_race_result_id_seq'::regclass),
    race_id character varying(20),
    race_name character varying(200),
    race_date date,
    grade character varying(10),
    venue character varying(50),
    distance integer,
    surface character varying(10),
    race_category character varying(30),
    winner_horse_name character varying(100),
    winner_horse_id character varying(20),
    image_url character varying(500),
    image_path character varying(500),
    analyzed boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.high_dividend_selection (
    id integer NOT NULL DEFAULT nextval('public.high_dividend_selection_id_seq'::regclass),
    race_id character varying(20),
    race_name character varying(200),
    venue character varying(50),
    race_date date,
    horse_count integer,
    favorite_odds double precision,
    odds_variance double precision,
    chaos_score double precision,
    selection_reason text,
    top5_json text,
    analyzed_at timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.horse_face_feature (
    id integer NOT NULL DEFAULT nextval('public.horse_face_feature_id_seq'::regclass),
    horse_name character varying(100),
    horse_id character varying(20),
    image_path character varying(500),
    finish_rank integer DEFAULT 1,
    race_category character varying(30),
    nose_shape character varying(100),
    eye_size character varying(50),
    eye_shape character varying(100),
    face_contour character varying(100),
    forehead_width character varying(50),
    nostril_size character varying(50),
    jaw_line character varying(50),
    overall_impression character varying(200),
    eye_aspect_ratio double precision,
    nose_width_ratio double precision,
    face_aspect_ratio double precision,
    jaw_strength_score double precision,
    overall_intensity double precision,
    analysis_count integer DEFAULT 1,
    avg_confidence double precision DEFAULT 0.0,
    raw_analysis text,
    is_winner boolean DEFAULT false,
    win_count integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.prediction_accuracy (
    id integer NOT NULL DEFAULT nextval('public.prediction_accuracy_id_seq'::regclass),
    prediction_id integer,
    race_name character varying(200),
    race_date date,
    race_category character varying(30),
    horse_name character varying(100),
    predicted_rank integer,
    actual_rank integer,
    hit boolean,
    top5_hit boolean,
    final_score double precision,
    recorded_at timestamp without time zone DEFAULT now(),
    top5hit boolean
);

CREATE TABLE IF NOT EXISTS public.prediction_result (
    id integer NOT NULL DEFAULT nextval('public.prediction_result_id_seq'::regclass),
    target_race_name character varying(200),
    target_race_date date,
    race_category character varying(30),
    horse_name character varying(100),
    horse_id character varying(20),
    image_path character varying(500),
    similarity_score double precision,
    diff_score double precision,
    final_score double precision,
    rank_position integer,
    analysis_detail text,
    created_at timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.race_entry (
    id integer NOT NULL DEFAULT nextval('public.race_entry_id_seq'::regclass),
    race_id character varying(20),
    race_name character varying(200),
    race_date date,
    race_category character varying(30),
    grade character varying(10),
    venue character varying(50),
    distance integer,
    surface character varying(10),
    horse_name character varying(100),
    horse_id character varying(20),
    post_position integer,
    horse_number integer,
    jockey_name character varying(100),
    image_path character varying(500),
    fetched_at timestamp without time zone DEFAULT now(),
    sex character varying(2)
);

CREATE TABLE IF NOT EXISTS public.race_odds (
    id integer NOT NULL DEFAULT nextval('public.race_odds_id_seq'::regclass),
    race_id character varying(20),
    race_name character varying(200),
    horse_name character varying(100),
    horse_id character varying(20),
    win_odds double precision,
    popularity integer,
    fetched_at timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.race_specific_accuracy (
    id integer NOT NULL DEFAULT nextval('public.race_specific_accuracy_id_seq'::regclass),
    race_name character varying(200),
    horse_name character varying(100),
    predicted_rank integer,
    actual_rank integer,
    hit boolean DEFAULT false,
    top5_hit boolean DEFAULT false,
    score double precision,
    data_source character varying(20) DEFAULT 'image'::character varying,
    recorded_at timestamp without time zone DEFAULT now(),
    top5hit boolean
);

CREATE TABLE IF NOT EXISTS public.race_specific_prediction (
    id bigint NOT NULL DEFAULT nextval('public.race_specific_prediction_id_seq'::regclass),
    analyzed_at timestamp without time zone,
    bottom_comment text,
    bottom_horses integer,
    bottom_pattern_json text,
    confidence_level integer,
    diff_comment text,
    race_name character varying(255),
    supplemental_count integer,
    top5comment text,
    top5horses integer,
    top5pattern_json text,
    total_horses integer,
    total_years integer
);

CREATE TABLE IF NOT EXISTS public.race_specific_result (
    id bigint NOT NULL DEFAULT nextval('public.race_specific_result_id_seq'::regclass),
    comment text,
    confidence_level integer,
    created_at timestamp without time zone,
    data_source character varying(255),
    feature_json text,
    horse_id character varying(255),
    horse_name character varying(255),
    image_path character varying(255),
    race_name character varying(255),
    rank_position integer,
    score double precision
);

CREATE TABLE IF NOT EXISTS public.races (
    id bigint NOT NULL DEFAULT nextval('public.races_id_seq'::regclass),
    date date NOT NULL,
    distance integer NOT NULL,
    location character varying(50),
    race_name character varying(100),
    track_condition character varying(255),
    CONSTRAINT races_distance_check CHECK ((distance >= 100))
);

CREATE TABLE IF NOT EXISTS public.stats_prediction (
    id integer NOT NULL DEFAULT nextval('public.stats_prediction_id_seq'::regclass),
    race_name character varying(200),
    horse_name character varying(100),
    horse_id character varying(20),
    rank_position integer,
    score double precision,
    score_detail text,
    comment text,
    created_at timestamp without time zone DEFAULT now(),
    image_path character varying(500),
    jockey_name character varying(100),
    horse_number integer,
    face_comment text,
    face_score double precision,
    face_analyzed_at timestamp without time zone
);


-- ============================================================
-- PRIMARY KEYS & CONSTRAINTS (idempotent via DO block)
-- ============================================================

DO $$ BEGIN
    ALTER TABLE ONLY public.face_image ADD CONSTRAINT face_image_pkey PRIMARY KEY (id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.grade_race_result ADD CONSTRAINT grade_race_result_pkey PRIMARY KEY (id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.grade_race_result ADD CONSTRAINT grade_race_result_race_id_key UNIQUE (race_id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.high_dividend_selection ADD CONSTRAINT high_dividend_selection_pkey PRIMARY KEY (id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.horse_face_feature ADD CONSTRAINT horse_face_feature_pkey PRIMARY KEY (id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.prediction_accuracy ADD CONSTRAINT prediction_accuracy_pkey PRIMARY KEY (id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.prediction_result ADD CONSTRAINT prediction_result_pkey PRIMARY KEY (id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.race_entry ADD CONSTRAINT race_entry_pkey PRIMARY KEY (id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.race_odds ADD CONSTRAINT race_odds_pkey PRIMARY KEY (id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.race_specific_accuracy ADD CONSTRAINT race_specific_accuracy_pkey PRIMARY KEY (id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.race_specific_prediction ADD CONSTRAINT race_specific_prediction_pkey PRIMARY KEY (id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.race_specific_result ADD CONSTRAINT race_specific_result_pkey PRIMARY KEY (id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.races ADD CONSTRAINT races_pkey PRIMARY KEY (id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.stats_prediction ADD CONSTRAINT stats_prediction_pkey PRIMARY KEY (id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.prediction_accuracy
        ADD CONSTRAINT prediction_accuracy_prediction_id_fkey
        FOREIGN KEY (prediction_id) REFERENCES public.prediction_result(id);
EXCEPTION WHEN OTHERS THEN NULL; END $$;
