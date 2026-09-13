package com.crabit.backend.simulation;

import java.nio.file.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.json.JsonMapper;

/** Disposable local application target. Uses backend migrations; accepts no target URL. */
class LocalTarget {
 public static void main(String[] args) throws Exception {
  if(args.length!=1)throw new IllegalArgumentException("private-ready-file required");
  try(var target=new SimulationPostgresClock()) {
   var ds=(DriverManagerDataSource)target.dataSource();var j=new JdbcTemplate(ds);
   // Testcontainers adds JDBC driver query options. The documented management CLI
   // takes a bare loopback URL; keep this same owned DB and separate credentials.
   var managementUrl=ds.getUrl().split("\\?",2)[0];
   if(!managementUrl.matches("jdbc:postgresql://(127\\.0\\.0\\.1|localhost):[0-9]+/[A-Za-z0-9_-]+"))
    throw new IllegalStateException("OWNED_TARGET_MUST_BE_LOOPBACK");
   new TransactionTemplate(new DataSourceTransactionManager(ds)).execute(ignored->{
    j.update("INSERT INTO academy(id,name) VALUES ('00000000-0000-0000-0000-000000000101','Local current academy'),('00000000-0000-0000-0000-000000000102','Excluded academy sentinel')");
    j.update("INSERT INTO student(id,nickname,age,age_provenance) VALUES ('00000000-0000-0000-0000-000000000201','Local current Owner',12,'PROVIDED')");
    j.update("INSERT INTO academy_membership(id,student_id,academy_id,joined_at) VALUES ('00000000-0000-0000-0000-000000000501','00000000-0000-0000-0000-000000000201','00000000-0000-0000-0000-000000000101',clock_timestamp())");
    j.update("INSERT INTO card_balance_account(id,student_id,academy_id,opened_at) VALUES ('00000000-0000-0000-0000-000000000301','00000000-0000-0000-0000-000000000201','00000000-0000-0000-0000-000000000101',clock_timestamp())");
    UUID event=UUID.randomUUID();
    j.update("INSERT INTO ledger_event(id,account_id,event_type,account_delta,occurred_at) VALUES (?,'00000000-0000-0000-0000-000000000301','CARD_BALANCE_CHANGE',23456,clock_timestamp())",event);
    j.update("INSERT INTO balance_observation(id,account_id,status,lookup_method,actual_card_balance,first_successful,previous_successful_balance,observed_at,balance_change_event_id,balance_change_event_type,balance_change_event_delta) VALUES (?,'00000000-0000-0000-0000-000000000301','SUCCEEDED','USER_REQUESTED',23456,true,0,clock_timestamp(),?,'CARD_BALANCE_CHANGE',23456)",UUID.randomUUID(),event);
    j.update("INSERT INTO wish(id,account_id,academy_id,purpose,target_amount,wish_amount,state,visibility,created_at,version) VALUES (?,'00000000-0000-0000-0000-000000000301','00000000-0000-0000-0000-000000000101','Local existing Owner goal',50000,0,'IN_PROGRESS','PRIVATE',clock_timestamp(),0)",UUID.randomUUID());
    return null;
   });
   var ready=Map.of("url",managementUrl,"user",ds.getUsername(),"password",ds.getPassword());
   Files.write(Path.of(args[0]),JsonMapper.builder().build().writeValueAsBytes(ready),StandardOpenOption.CREATE_NEW);
   while(System.in.read()!=-1) { }
  }
 }
}
