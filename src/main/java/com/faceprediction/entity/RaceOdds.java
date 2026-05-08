package com.faceprediction.entity;

import java.time.LocalDateTime;

import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.persistence.Table;

@Entity
@Table(name = "race_odds")
public class RaceOdds {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String raceId;
    private String raceName;
    private String horseName;
    private String horseId;
    private Double winOdds;
    private Integer popularity;
    private LocalDateTime fetchedAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getRaceId() { return raceId; }
    public void setRaceId(String raceId) { this.raceId = raceId; }
    public String getRaceName() { return raceName; }
    public void setRaceName(String raceName) { this.raceName = raceName; }
    public String getHorseName() { return horseName; }
    public void setHorseName(String horseName) { this.horseName = horseName; }
    public String getHorseId() { return horseId; }
    public void setHorseId(String horseId) { this.horseId = horseId; }
    public Double getWinOdds() { return winOdds; }
    public void setWinOdds(Double winOdds) { this.winOdds = winOdds; }
    public Integer getPopularity() { return popularity; }
    public void setPopularity(Integer popularity) { this.popularity = popularity; }
    public LocalDateTime getFetchedAt() { return fetchedAt; }
    public void setFetchedAt(LocalDateTime fetchedAt) { this.fetchedAt = fetchedAt; }
}
