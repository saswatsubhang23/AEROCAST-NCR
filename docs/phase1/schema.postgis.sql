
create extension if not exists postgis;

create table if not exists env_source (
  source        text primary key,
  description   text not null,
  licence       text not null,
  attribution   text not null,
  native_resolution_km double precision,
  update_cadence text
);

create table if not exists env_station (
  station_id    bigint primary key,
  name          text not null,
  provider      text,
  zone          text,
  geom          geometry(Point, 4326) not null,
  datetime_first timestamptz,
  datetime_last  timestamptz
);
create index if not exists ix_env_station_geom on env_station using gist (geom);

create table if not exists env_cell (
  cell_id       text primary key,           -- e.g. cams:0.4:28.400,77.200
  source        text not null references env_source(source),
  resolution_km double precision not null,
  geom          geometry(Polygon, 4326) not null
);
create index if not exists ix_env_cell_geom on env_cell using gist (geom);

create table if not exists env_record (
  record_id     char(40) primary key,
  kind          text not null check (kind in ('observation','forecast','analysis','interpolation','simulation')),
  source        text not null references env_source(source),
  variable      text not null,
  value         double precision,
  unit          text not null,
  original_value double precision,
  original_unit text,
  valid_from    timestamptz not null,
  valid_to      timestamptz not null,
  issued_at     timestamptz,
  retrieved_at  timestamptz not null,
  location_id   text not null,
  geom          geometry(Point, 4326) not null,
  support       text not null check (support in ('point','cell')),
  resolution_km double precision,
  quality_flags text[] not null default '{}',
  usable        boolean not null,
  check (valid_to > valid_from),
  check (kind <> 'forecast' or issued_at is not null),
  check (kind <> 'observation' or issued_at is null),
  check (support <> 'cell' or resolution_km is not null),
  check (value is not null or not usable)
);
create index if not exists ix_env_record_var_time on env_record (variable, valid_to desc);
create index if not exists ix_env_record_loc on env_record (location_id, variable, valid_to desc);
create index if not exists ix_env_record_geom on env_record using gist (geom);
create index if not exists ix_env_record_kind on env_record (kind, source);
create index if not exists ix_env_record_time_brin on env_record using brin (valid_to);

create table if not exists exposure_cell (
  cell_id       text primary key,
  geom          geometry(Polygon, 4326) not null,
  population    double precision,           -- people in the cell (WorldPop / GHSL), null until loaded
  pop_source    text,
  pop_year      integer,
  children_u5   double precision,
  adults_65plus double precision
);
create index if not exists ix_exposure_cell_geom on exposure_cell using gist (geom);

create table if not exists sensitive_site (
  site_id       bigserial primary key,
  kind          text not null check (kind in ('hospital','school','childcare','eldercare','other')),
  name          text,
  geom          geometry(Point, 4326) not null,
  source        text not null
);
create index if not exists ix_sensitive_site_geom on sensitive_site using gist (geom);


insert into env_source (source, description, licence, attribution, native_resolution_km, update_cadence) values
 ('openaq','OpenAQ v3 hourly station observations','per provider','OpenAQ',null,'hourly, provider lag of hours to days'),
 ('xkdr','xKDR India air-quality archive (CPCB CAAQM, US Embassy)','not stated','xKDR',null,'archive, ends 2025-09 for CPCB'),
 ('open_meteo_forecast','Open-Meteo forecast API (ECMWF IFS and others)','CC BY 4.0; free API non-commercial','Open-Meteo.com',9,'hourly model runs'),
 ('open_meteo_archive','Open-Meteo historical weather (ERA5 / IFS)','CC BY 4.0; free API non-commercial','Open-Meteo.com',9,'about one day lag'),
 ('open_meteo_air_quality','Open-Meteo air quality (ECMWF CAMS)','CC BY 4.0; Copernicus','Copernicus Atmosphere Monitoring Service; Open-Meteo.com',44,'hourly'),
 ('aerocast_ml','AEROCAST trained station forecast','derived','AEROCAST NCR',null,'on request'),
 ('aerocast_idw','AEROCAST inverse-distance interpolation','derived','AEROCAST NCR',null,'on request'),
 ('aerocast_transport','AEROCAST passive transport simulation','derived','AEROCAST NCR',null,'on request'),
 ('aerocast_coupled','AEROCAST coupled multi-species simulation','derived','AEROCAST NCR',null,'on request')
on conflict (source) do nothing;

