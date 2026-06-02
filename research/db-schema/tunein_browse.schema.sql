-- tunein_browse.db
-- =============================================
CREATE TABLE FTF010 (                 /* station tbl      */ 
    PROP3601        INTEGER,          /* object id        */ 
    PROPAB00        TEXT,             /* station id       */ 
    PROP3006        INTEGER,          /* service id       */ 
    PROPAB01        TEXT,             /* icon URL         */ 
    PROPAB0C        TEXT,             /* list icon URL    */ 
    PROP78D9        BLOB,             /* thumbnail        */ 
    PROPAB04        INTEGER,          /* icon reuse       */ 
    PROP30F0        INTEGER,          /* color picked info*/ 
     PROPAB05        INTEGER,          /* bitrate          */ 
    PROPAB06        TEXT,             /* Codec            */ 
    PROPAB09        INTEGER,          /* sort index       */ 
     PROPFF22        INTEGER NOT NULL, /* last play flag   */ 
    PRIMARY KEY(PROP3601)                                    
);
CREATE INDEX idx_FTF010_PROP3006 ON FTF010(PROP3006);
CREATE INDEX idx_FTF010_PROPAB09 ON FTF010(PROPAB09);
CREATE INDEX idx_FTF010_PROPAB05 ON FTF010(PROPAB05);
CREATE TABLE FTF0FF (
    PROP3601        INTEGER NOT NULL, /* id           */ 
    PROPFFF0        INTEGER,          /* value(int)   */ 
    PROPFFF1        TEXT,             /* value(text)  */ 
    PRIMARY KEY(PROP3601)                                
);

-- ROW COUNTS --
-- FTF010                                   673 rows
-- FTF0FF                                   4 rows
