-- radiko_browse.db
-- =============================================
CREATE TABLE FTF010 (                 /* station tbl      */ 
    PROP3601        INTEGER,          /* object id        */ 
    PROPAB00        TEXT,             /* station id       */ 
    PROP3006        INTEGER,          /* service id       */ 
    PROPAB0B        TEXT,             /* area id          */ 
    PROPAB01        TEXT,             /* icon URL         */ 
    PROPAB0C        TEXT,             /* list icon URL    */ 
    PROP78D9        BLOB,             /* thumbnail        */ 
    PROPAB04        INTEGER,          /* icon reuse       */ 
    PROP3046        INTEGER NOT NULL, /* playing count    */ 
    PROP30F0        INTEGER,          /* color picked info*/ 
     PRIMARY KEY(PROP3601)                                    
);
CREATE INDEX idx_FTF010_PROP3006 ON FTF010(PROP3006);
CREATE INDEX idx_FTF010_PROPAB03 ON FTF010(PROPAB0B);
CREATE TABLE FTF0FF (
    PROP3601        INTEGER NOT NULL, /* id           */ 
    PROPFFF0        INTEGER,          /* value(int)   */ 
    PROPFFF1        TEXT,             /* value(text)  */ 
    PRIMARY KEY(PROP3601)                                
);

-- ROW COUNTS --
-- FTF010                                   0 rows
-- FTF0FF                                   3 rows
