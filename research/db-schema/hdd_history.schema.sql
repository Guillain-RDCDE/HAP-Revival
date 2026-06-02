-- hdd_history.db
-- =============================================
CREATE TABLE FTF080 (
    PROP3601        INTEGER NOT NULL, /* list id           */ 
    PROPC031        TEXT,             /* sql statement     */ 
    PROPC034        INTEGER NOT NULL, /* auto sync flag    */ 
    PRIMARY KEY(PROP3601)                                     
);
CREATE INDEX idx_FTF080_PROPC031 ON FTF080(PROPC031);
CREATE INDEX idx_FTF080_PROPC034 ON FTF080(PROPC034);
CREATE TABLE FTF081 (
    PROP3601 INTEGER NOT NULL,        /* list id           */ 
    PROPC030 INTEGER NOT NULL,        /* history id        */ 
    PROPC032 TEXT,                    /* text parameter    */ 
    PROPC033 BLOB,                    /* binary parameter  */ 
    PRIMARY KEY(PROP3601)                                     
);
CREATE INDEX idx_FTF081_PROPC030 ON FTF081(PROPC030);
CREATE INDEX idx_FTF081_PROPC032 ON FTF081(PROPC032);
CREATE INDEX idx_FTF081_PROPC033 ON FTF081(PROPC033);
CREATE TABLE FTF0FF (
    PROP3601        INTEGER NOT NULL, /* id           */ 
    PROPFFF0        INTEGER,          /* value(int)   */ 
    PROPFFF1        TEXT,             /* value(text)  */ 
    PRIMARY KEY(PROP3601)                                
);

-- ROW COUNTS --
-- FTF080                                   0 rows
-- FTF081                                   0 rows
-- FTF0FF                                   3 rows
