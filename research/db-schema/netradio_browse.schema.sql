-- netradio_browse.db
-- =============================================
CREATE TABLE FTF010 (                 /* station tbl      */ 
    PROP3601        INTEGER,          /* object id        */ 
    PROPAB00        TEXT,             /* station id       */ 
    PROP3006        INTEGER,          /* service id       */ 
    PROP7020        TEXT,             /* name             */ 
    PROPAB01        TEXT,             /* icon URL         */ 
    PROPAB02        TEXT,             /* play URL         */ 
    PROPAB03        INTEGER,          /* location         */ 
    PROP7045        INTEGER,          /* genre            */ 
    PROP78D9        BLOB,             /* thumbnail        */ 
    PROP087E        INTEGER,          /* rating vlaue     */ 
    PROPAB04        INTEGER,          /* icon size        */ 
    PROPAB05        INTEGER,          /* band width       */ 
    PROPAB06        TEXT,             /* mime type        */ 
    PROPAB07        TEXT,             /* name(yomi)       */ 
    PROP7065        TEXT,             /* name(sort)       */ 
    PROP7221        TEXT,             /* name(initial)    */ 
    PROP3046        INTEGER NOT NULL, PROP7061        TEXT            /* description      */, PROP30F0        INTEGER         /* color picked info*/, PROP58DF        INTEGER         /* playable         */, PROPAB08        TEXT            /* band width(text) */, PROPAB09        INTEGER         /* sort index       */, PROPFF22        INTEGER         /* last play flag   */, /* playing count    */ 
    PRIMARY KEY(PROP3601)                                    
);
CREATE INDEX idx_FTF010_PROP3006 ON FTF010(PROP3006);
CREATE INDEX idx_FTF010_PROPAB03 ON FTF010(PROPAB03);
CREATE INDEX idx_FTF010_PROP7045 ON FTF010(PROP7045);
CREATE INDEX idx_FTF010_PROP7065 ON FTF010(PROP7065);
CREATE INDEX idx_FTF010_PROP7221 ON FTF010(PROP7221);
CREATE INDEX idx_FTF010_PROP3046 ON FTF010(PROP3046);
CREATE TABLE FTF011 (                 /* st genre tbl */ 
    PROP3601        INTEGER NOT NULL, /* id           */ 
    PROP7020        TEXT,             /* genre name   */ 
    PROPAA20        TEXT,             /* name(yomi)   */ 
    PROP7065        TEXT,             /* name(sort)   */ 
    PROP7221        TEXT,             /* name(initial)*/ 
    PRIMARY KEY(PROP3601)                                
);
CREATE INDEX idx_FTF011_PROP7065 ON FTF011(PROP7065);
CREATE INDEX idx_FTF011_PROP7221 ON FTF011(PROP7221);
CREATE TABLE FTF012 (                 /* country tbl  */ 
    PROP3601        INTEGER NOT NULL, /* id           */ 
    PROP7020        TEXT,             /* country name */ 
    PROPAB21        TEXT,             /* name(yomi)   */ 
    PROP7065        TEXT,             /* name(sort)   */ 
    PROP7221        TEXT,             /* name(initial)*/ 
    PRIMARY KEY(PROP3601)                                
);
CREATE INDEX idx_FTF012_PROP7065 ON FTF012(PROP7065);
CREATE INDEX idx_FTF012_PROP7221 ON FTF012(PROP7221);
CREATE TABLE FTF0FF (
    PROP3601        INTEGER NOT NULL, /* id           */ 
    PROPFFF0        INTEGER,          /* value(int)   */ 
    PROPFFF1        TEXT,             /* value(text)  */ 
    PRIMARY KEY(PROP3601)                                
);
CREATE INDEX idx_FTF010_PROPAB05 ON FTF010(PROPAB05);
CREATE INDEX idx_FTF010_PROPAB09 ON FTF010(PROPAB09);
CREATE INDEX idx_FTF010_PROPFF22 ON FTF010(PROPFF22);

-- ROW COUNTS --
-- FTF010                                   0 rows
-- FTF011                                   1 rows
-- FTF012                                   1 rows
-- FTF0FF                                   4 rows
