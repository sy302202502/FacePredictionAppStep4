package com.faceprediction.service;

import java.util.ArrayList;
import java.util.List;

/**
 * 買い目提案の1券種分（例: 馬連 ◎-○▲△注 流し 4点）。
 * hit はレース結果が確定しているときだけ入る（未確定は null）。
 */
public class BetLine {

    /** 買い目の1組（表示ラベルと的中フラグ） */
    public static class Combo {
        private final String label;
        private final Boolean hit;
        private final Integer payout;

        public Combo(String label, Boolean hit, Integer payout) {
            this.label = label;
            this.hit = hit;
            this.payout = payout;
        }

        public String getLabel() { return label; }
        public Boolean getHit() { return hit; }
        /** 100円あたりの払戻（払戻表で判定したときの的中組のみ） */
        public Integer getPayout() { return payout; }
    }

    private final String type;
    private final String method;
    private final List<Combo> combos = new ArrayList<>();

    public BetLine(String type, String method) {
        this.type = type;
        this.method = method;
    }

    public void addCombo(Combo combo) { combos.add(combo); }

    public String getType() { return type; }
    public String getMethod() { return method; }
    public List<Combo> getCombos() { return combos; }
    public int getPoints() { return combos.size(); }

    /** 払戻の合計（100円×各組）。払戻表で判定していなければ null */
    public Integer getReturnAmount() {
        if (combos.isEmpty() || combos.get(0).getHit() == null) return null;
        if (combos.stream().allMatch(c -> c.getPayout() == null) && getHit()) return null;
        return combos.stream().filter(c -> c.getPayout() != null).mapToInt(Combo::getPayout).sum();
    }

    /** 1組でも的中していれば true。結果未確定なら null */
    public Boolean getHit() {
        if (combos.isEmpty() || combos.get(0).getHit() == null) return null;
        return combos.stream().anyMatch(c -> Boolean.TRUE.equals(c.getHit()));
    }
}
