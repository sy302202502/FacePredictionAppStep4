package com.faceprediction.entity;

import java.time.LocalDate;
import java.time.LocalDateTime;

import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.persistence.PrePersist;
import javax.persistence.Table;

@Entity
@Table(name = "race_entry")
public class RaceEntry {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String raceId;
    private String raceName;
    private LocalDate raceDate;
    private String raceCategory;
    private String grade;
    private String venue;
    private Integer distance;
    private String surface;
    private String horseName;
    private String horseId;
    private Integer postPosition;
    private Integer horseNumber;
    private String jockeyName;
    private String imagePath;
    private LocalDateTime fetchedAt;

    public RaceEntry() {}

    @PrePersist
    protected void onCreate() {
        if (fetchedAt == null) fetchedAt = LocalDateTime.now();
    }

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getRaceId() { return raceId; }
    public void setRaceId(String raceId) { this.raceId = raceId; }
    public String getRaceName() { return raceName; }
    public void setRaceName(String raceName) { this.raceName = raceName; }
    public LocalDate getRaceDate() { return raceDate; }
    public void setRaceDate(LocalDate raceDate) { this.raceDate = raceDate; }
    public String getRaceCategory() { return raceCategory; }
    public void setRaceCategory(String raceCategory) { this.raceCategory = raceCategory; }
    public String getGrade() { return grade; }
    public void setGrade(String grade) { this.grade = grade; }
    public String getVenue() { return venue; }
    public void setVenue(String venue) { this.venue = venue; }
    public Integer getDistance() { return distance; }
    public void setDistance(Integer distance) { this.distance = distance; }
    public String getSurface() { return surface; }
    public void setSurface(String surface) { this.surface = surface; }
    public String getHorseName() { return horseName; }
    public void setHorseName(String horseName) { this.horseName = horseName; }
    public String getHorseId() { return horseId; }
    public void setHorseId(String horseId) { this.horseId = horseId; }
    public Integer getPostPosition() { return postPosition; }
    public void setPostPosition(Integer postPosition) { this.postPosition = postPosition; }
    public Integer getHorseNumber() { return horseNumber; }
    public void setHorseNumber(Integer horseNumber) { this.horseNumber = horseNumber; }
    public String getJockeyName() { return jockeyName; }
    public void setJockeyName(String jockeyName) { this.jockeyName = jockeyName; }
    public String getImagePath() { return imagePath; }
    public void setImagePath(String imagePath) { this.imagePath = imagePath; }
    public LocalDateTime getFetchedAt() { return fetchedAt; }
    public void setFetchedAt(LocalDateTime fetchedAt) { this.fetchedAt = fetchedAt; }
}
