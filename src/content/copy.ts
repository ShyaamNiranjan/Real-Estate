export type ScrollBeat = {
  id: string
  side: 'left' | 'right'
  at: number
  label: string
  text: string
}

export type Residence = {
  name: string
  meta: string
  blurb: string
  price: string
  image: string
}

export type Amenity = {
  title: string
  text: string
}

export const copy = {
  brand: {
    name: 'AURELIA',
    tagline: 'Daylight, held in stone and glass.',
    nav: ['Residences', 'Amenities', 'Location', 'Enquire'] as const,
  },
  hero: {
    brand: 'AURELIA',
    line: 'Light is the first material.',
    support: 'A modern villa of white masonry, warm wood, and glass that never closes.',
    scrollHint: 'Scroll to enter',
  },
  scrollBeats: [
    {
      id: 'approach',
      side: 'left',
      at: 0.05,
      label: 'The Facade',
      text: 'White masonry, warm wood, black glass. Nothing raised its voice.',
    },
    {
      id: 'threshold',
      side: 'right',
      at: 0.26,
      label: 'The Threshold',
      text: 'A walnut door, open. The house is already bright.',
    },
    {
      id: 'arrival',
      side: 'left',
      at: 0.48,
      label: 'The Room',
      text: 'Double-height glass. Marble, dark cabinetry, floors like still water.',
    },
    {
      id: 'reveal',
      side: 'right',
      at: 0.7,
      label: 'The Table',
      text: 'Set for eight. Behind it, the glass slides away.',
    },
    {
      id: 'outdoors',
      side: 'left',
      at: 0.9,
      label: 'The Water',
      text: 'Pool, deck, cabana. The garden closes around you.',
    },
  ] satisfies ScrollBeat[],
  site: {
    intro: {
      eyebrow: 'The Flagship Residence',
      title: 'A house planned around the middle of the day.',
      body: "AURELIA is built in three materials and one idea: let the light through. Rooms run long and uninterrupted, from the entry to the glass wall at the back, then out to water and deck. Everything you touch is quiet — honed stone, oiled wood, steel drawn as thin as it will go.",
    },
    residences: [
      {
        name: 'The Garden House',
        meta: '3 beds · 3.5 baths · 3,280 sq ft · single level',
        blurb: 'A low, wide plan that opens along its full length to the lawn.',
        price: 'From $4.9M',
        image: '/frames/frame-01.jpg',
      },
      {
        name: 'The Glass Wing',
        meta: '4 beds · 4.5 baths · 4,600 sq ft · two levels',
        blurb: 'A double-height living room with the kitchen kept dark and calm beside it.',
        price: 'From $6.7M',
        image: '/frames/frame-05.jpg',
      },
      {
        name: 'The Pool Pavilion',
        meta: '5 beds · 5.5 baths · 6,100 sq ft · two levels with cabana',
        blurb: 'The largest plan, wrapped on three sides by deck and water.',
        price: 'From $9.4M',
        image: '/frames/frame-10.jpg',
      },
    ] satisfies Residence[],
    amenities: [
      {
        title: 'The Long Pool',
        text: 'Twenty-two metres of still water in teal glazed tile, edged in pale stone.',
      },
      {
        title: "Chef's Kitchen",
        text: 'A single slab of marble, full-height cabinetry, and everything else out of sight.',
      },
      {
        title: 'Shaded Cabana',
        text: "Linen curtains, a fan, and the coolest place on the property at two o'clock.",
      },
      {
        title: 'Private Grounds',
        text: 'Clipped hedge and mature trees on every boundary, so the garden stays yours.',
      },
    ] satisfies Amenity[],
    location: {
      title: 'Eleven minutes from the last traffic light.',
      body: 'AURELIA sits at the quiet end of a mature residential road, where the lots widen and the noise stops. The city is close enough to reach before lunch and far enough to forget by evening.',
      points: [
        '11 minutes to the central district',
        'Walking distance to the park and the old market street',
        '28 minutes to the international terminal',
      ],
    },
    enquire: {
      title: 'Come and stand in it.',
      body: "The plans explain the house; the light explains the rest. Viewings are arranged one at a time, with the architect's drawings on the table.",
      cta: 'Request a private viewing',
      note: 'By appointment, Tuesday to Saturday. Two residences remain.',
    },
    footer: {
      line: 'AURELIA · A fictional residence, built for demonstration.',
    },
  },
} as const
