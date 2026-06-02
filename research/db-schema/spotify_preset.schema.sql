-- spotify_preset.db
-- =============================================
CREATE TABLE config (version INTEGER UNIQUE);
CREATE TABLE preset (id INTEGER PRIMARY KEY, name CHAR(255), dispOrder INTEGER, presetBlob CHAR(2752), lastPlay INTEGER, playbackSourceUri CHAR(128));

-- ROW COUNTS --
-- config                                   1 rows
-- preset                                   0 rows
