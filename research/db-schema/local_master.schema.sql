-- local_master.db
-- =============================================
CREATE TABLE FT000A (
    PROP3601        INTEGER NOT NULL, /* object id           */ 
    PROP705C        TEXT,             /* cover art path      */ 
    PROP30F0        INTEGER,          /* color picked        */ 
    PROP707A        TEXT,             /* product id          */ 
    PROP78A4        BLOB,             /* toc                 */ 
    PROP30A5        INTEGER,          /* album gain          */ 
    PROP60E1        FLOAT,            /* 12tone peak         */ 
    PROPAA13        INTEGER NOT NULL DEFAULT 0, /* coverart type */ 
    PROPAA14        INTEGER NOT NULL DEFAULT 0, /* coverart size */ 
    PRIMARY KEY(PROP3601)                                    
                                                             
);
CREATE TABLE FTF0FF (
    PROP3601        INTEGER NOT NULL, /* id           */ 
    PROPFFF0        INTEGER,          /* value(int)   */ 
    PROPFFF1        TEXT,             /* value(text)  */ 
    PRIMARY KEY(PROP3601)                                
);

-- ROW COUNTS --
-- FT000A                                   5677 rows
-- FTF0FF                                   3 rows
