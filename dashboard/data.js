// Demo fixture for the M.A.N.D.A.R.I.N dashboard.
//
// EVERYTHING HERE IS FICTIONAL. Island names, populations, timetables and the
// facility list are invented so the UI and simulator can be built before real
// data is collected. Replace this file (or the API that serves the same shape)
// with real, sourced records later. Keep the field names stable.

window.MANDARIN_FIXTURE = {
  meta: {
    scenarioName: "Demo atoll",
    operatingDate: "2026-11-03", // a Tuesday
    weekday: "tue",
    classification: "demo",
  },

  // The demo network is drawn inside a real atoll on the map so the zoom works,
  // but its islands, names and timetable are invented. Change atollId to move it.
  atollId: "L",

  hub: "AC",
  transferBufferMin: 15, // minimum time to change boats at an island
  serviceWindow: { start: "05:00", end: "22:00" }, // ferries may only run inside this window

  // x/y are schematic positions in a 600x430 frame, fitted into the atoll's
  // bounding box on the map. They are not real island coordinates.
  islands: [
    { id: "AC", name: "Atoll Centre", population: 2400, schoolAge: 600, secondaryStudents: 0, ownSecondary: true,
      hasHospital: true, hasSecondarySchool: true, harbourToFacilityMin: 10, x: 300, y: 215 },
    { id: "A", name: "Island A", population: 1200, schoolAge: 330, secondaryStudents: 150, ownSecondary: true, x: 185, y: 140 },
    { id: "B", name: "Island B", population: 800, schoolAge: 300, secondaryStudents: 120, ownSecondary: false, x: 430, y: 85 },
    { id: "C", name: "Island C", population: 600, schoolAge: 220, secondaryStudents: 90, ownSecondary: false, x: 455, y: 330 },
    { id: "D", name: "Island D", population: 450, schoolAge: 130, secondaryStudents: 55, ownSecondary: true, x: 75, y: 70 },
    { id: "E", name: "Island E", population: 350, schoolAge: 110, secondaryStudents: 50, ownSecondary: false, x: 285, y: 375 },
    { id: "F", name: "Island F", population: 900, schoolAge: 310, secondaryStudents: 140, ownSecondary: false, x: 125, y: 300 },
    { id: "G", name: "Island G", population: 500, schoolAge: 170, secondaryStudents: 70, ownSecondary: false, x: 530, y: 200 },
  ],

  // Each trip is one scheduled service. Shifting a trip moves every stop time
  // together so travel durations are preserved.
  trips: [
    { id: "T-A1", days: "all", stops: [{ island: "A", dep: "07:55" }, { island: "AC", arr: "08:35" }] },
    { id: "T-A2", days: "all", stops: [{ island: "AC", dep: "13:00" }, { island: "A", arr: "13:40" }] },
    { id: "T-A3", days: "all", stops: [{ island: "AC", dep: "16:30" }, { island: "A", arr: "17:10" }] },
    { id: "T-B1", days: "all", stops: [{ island: "B", dep: "09:30" }, { island: "AC", arr: "10:30" }] },
    { id: "T-B2", days: "all", stops: [{ island: "AC", dep: "15:30" }, { island: "B", arr: "16:30" }] },
    { id: "T-C1", days: "all", stops: [{ island: "C", dep: "06:30" }, { island: "AC", arr: "07:20" }] },
    { id: "T-C2", days: "all", stops: [{ island: "AC", dep: "11:30" }, { island: "C", arr: "12:20" }] },
    { id: "T-D1", days: "all", stops: [{ island: "D", dep: "07:20" }, { island: "A", arr: "07:50" }] },
    { id: "T-D2", days: "all", stops: [{ island: "A", dep: "14:00" }, { island: "D", arr: "14:30" }] },
    { id: "T-E1", days: ["mon", "wed", "sat"], stops: [{ island: "E", dep: "06:45" }, { island: "AC", arr: "08:00" }] },
    { id: "T-E2", days: ["mon", "wed", "sat"], stops: [{ island: "AC", dep: "14:30" }, { island: "E", arr: "15:45" }] },
    { id: "T-F1", days: "all", stops: [{ island: "F", dep: "07:30" }, { island: "AC", arr: "08:20" }] },
    { id: "T-F2", days: "all", stops: [{ island: "AC", dep: "15:00" }, { island: "F", arr: "15:50" }] },
    { id: "T-G1", days: "all", stops: [{ island: "G", dep: "06:20" }, { island: "AC", arr: "07:05" }] },
    { id: "T-G2", days: "all", stops: [{ island: "AC", dep: "14:00" }, { island: "G", arr: "14:40" }] },
  ],

  // Journey rules: the trips being tested. Activity starts at arriveBy and
  // lasts activityMin; the return search starts after the walk back.
  rules: [
    { id: "health", label: "Hospital appointment", short: "Hospital", eligible: "residents", destination: "AC",
      earliestStart: "05:00", arriveBy: "10:00", activityMin: 120, homeBy: "18:00" },
    { id: "school", label: "Secondary school day", short: "School", eligible: "secondary_students", destination: "AC",
      earliestStart: "05:00", arriveBy: "07:30", activityMin: 360, homeBy: "17:00" },
  ],

  // One-click demo scenarios for the presentation.
  presets: [
    { label: "Island B ferry to 08:00", tripId: "T-B1", shiftMin: -90 },
    { label: "Island A ferry 15 min later", tripId: "T-A1", shiftMin: 15 },
    { label: "Last ferry to Island C at 14:00", tripId: "T-C2", shiftMin: 150 },
    { label: "Island F ferry to 06:30", tripId: "T-F1", shiftMin: -60 },
    { label: "Island A ferry 90 min later", tripId: "T-A1", shiftMin: 90, note: "shows a loss" },
  ],

  sources: [
    { dataset: "Map: island and reef outlines", planned: "OpenStreetMap contributors (ODbL), simplified; used as-is", classification: "observed" },
    { dataset: "Islands and population", planned: "Census 2022, Maldives Bureau of Statistics", classification: "demo" },
    { dataset: "Ferry timetables", planned: "Public ferry schedules (RTL / MTCC, Transport Authority)", classification: "demo" },
    { dataset: "Health facilities", planned: "Ministry of Health / HPA facility list", classification: "demo" },
    { dataset: "School locations", planned: "Ministry of Education school list", classification: "demo" },
    { dataset: "Demo island positions", planned: "Real island coordinates from OpenStreetMap", classification: "demo" },
    { dataset: "Journey rules", planned: "Team assumptions (times, buffers, durations)", classification: "assumed" },
  ],
};
