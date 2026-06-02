-- netradio_management.db
-- =============================================
CREATE TABLE FTF0F0 ( 
    PROP3601        INTEGER NOT NULL, /* object id    */ 
    PROPFF00        TEXT,             /* serial id    */ 
    PROPFF01        TEXT,             /* last connect */ 
    PRIMARY KEY(PROP3601)                                
);
CREATE TABLE FTF0F1 ( 
    PROP3601        INTEGER NOT NULL, /* object id    */ 
    PROPFF10        TEXT,             /* device id    */ 
    PROP6874        TEXT,             /* last play    */ 
    PRIMARY KEY(PROP3601)                                
);
CREATE TABLE FTF0F2 (
    PROP3601        INTEGER NOT NULL, /* list id              */ 
    PROP106E        INTEGER NOT NULL, /* track num            */ 
    PROP705E        INTEGER NOT NULL, /* list type            */ 
    PROPAA70        INTEGER NOT NULL, /* modify no            */ 
    PROP2053        INTEGER NOT NULL, /* last play index      */ 
    PROP4077        FLOAT,            /* last play resume     */ 
    PROPFF20        INTEGER NOT NULL, /* shuffle type         */ 
    PROPFF21        INTEGER NOT NULL, /* repeat type          */ 
    PROPFF22        INTEGER NOT NULL, /* last play flag       */ 
    PRIMARY KEY(PROP3601)                                        
);
CREATE TABLE FTF0F3 (
    PROP3601        INTEGER NOT NULL, /* track id        */ 
    PROP3006        INTEGER NOT NULL, /* list id         */ 
    PROP2053        INTEGER NOT NULL, /* original index  */ 
    PROPFF30        INTEGER NOT NULL, /* play index      */ 
    PRIMARY KEY(PROP3601,PROP3006,PROP2053)                 
);
CREATE INDEX idx_FTF0F3_PROP2053 ON FTF0F3(PROP2053);
CREATE INDEX idx_FTF0F3_PROPFF30 ON FTF0F3(PROPFF30);
CREATE TABLE FTF0F4 (                 /* update ldb   */ 
    PROP3601        INTEGER NOT NULL, /* order id     */ 
    PROP705E        INTEGER NOT NULL, /* ctrl type    */ 
    PROPAA70        INTEGER NOT NULL, /* modify no    */ 
    PROPFF40        INTEGER NOT NULL, /* command type */ 
    PROPE040        INTEGER NOT NULL, /* table no     */ 
    PRIMARY KEY(PROP3601,PROP705E,PROPAA70)              
);
CREATE TABLE FTF0F5 (                 /* update ldb   */ 
    PROP3006        INTEGER NOT NULL, /* parent id    */ 
    PROPAA70        INTEGER NOT NULL, /* modify no    */ 
    PROPE041        INTEGER NOT NULL, /* field no     */ 
    PROP7020        TEXT,             /* update data  */ 
    PROP705E        INTEGER NOT NULL, /* ctrl type    */ 
    PRIMARY KEY(PROP3006,PROPAA70,PROPE041)              
);
CREATE TABLE FTF0F6 (
    PROP3601        INTEGER NOT NULL, /* list id              */ 
    PROP106E        INTEGER NOT NULL, /* track num            */ 
    PROP705E        INTEGER NOT NULL, /* list type            */ 
    PROPAA70        INTEGER NOT NULL, /* modify no            */ 
    PROP2053        INTEGER NOT NULL, /* last play index      */ 
    PROPFF22        INTEGER NOT NULL, /* last play flag       */ 
    PROP3006        INTEGER NOT NULL  /* service ID           */ 
   ,PRIMARY KEY(PROP3601,PROP3006)                               
);
CREATE TABLE FTF0F7 (
    PROPAB00        TEXT,             /* station id      */ 
    PROP3006        INTEGER NOT NULL, /* list id         */ 
    PROP2053        INTEGER NOT NULL  /* original index  */ 
   ,PROPAB0A        INTEGER NOT NULL DEFAULT 1  /* service id  */ 
   ,PRIMARY KEY(PROPAB00,PROP3006,PROP2053,PROPAB0A)        
);
CREATE INDEX idx_FTF0F7_PROP2053 ON FTF0F7(PROP2053);
CREATE TABLE FTF0FF (
    PROP3601        INTEGER NOT NULL, /* id           */ 
    PROPFFF0        INTEGER,          /* value(int)   */ 
    PROPFFF1        TEXT,             /* value(text)  */ 
    PRIMARY KEY(PROP3601)                                
);

-- ROW COUNTS --
-- FTF0F0                                   1 rows
-- FTF0F1                                   1 rows
-- FTF0F2                                   0 rows
-- FTF0F3                                   0 rows
-- FTF0F4                                   0 rows
-- FTF0F5                                   0 rows
-- FTF0F6                                   1 rows
-- FTF0F7                                   0 rows
-- FTF0FF                                   3 rows
