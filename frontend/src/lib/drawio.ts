export function escXml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** Regions offered in the diagram form. */
export const AWS_REGIONS = [
  'us-east-1',
  'us-east-2',
  'us-west-1',
  'us-west-2',
  'ap-south-1',
  'ap-southeast-1',
  'ap-southeast-2',
  'ap-northeast-1',
  'eu-central-1',
  'eu-west-1',
  'eu-west-2',
  'sa-east-1',
] as const

type Cell = {
  id: string
  value: string
  style: string
  x: number
  y: number
  w: number
  h: number
  parent?: string
}

/**
 * AWS architecture icon.
 *
 * The `aws4` stencils are monochrome, `aspect="fixed"` paths that carry no fill
 * of their own, so the colour has to come from the style. Names are the
 * stencil names with spaces replaced by underscores, lower-cased, e.g. the
 * "rds multi az" stencil is `mxgraph.aws4.rds_multi_az`.
 *
 * Colours are the AWS Architecture Icons category palette.
 */
function awsIcon(stencil: string, fill: string): string {
  return (
    'sketch=0;outlineConnect=0;aspect=fixed;html=1;whiteSpace=wrap;' +
    'verticalLabelPosition=bottom;verticalAlign=top;align=center;fontSize=11;fontColor=#334155;' +
    `fillColor=${fill};strokeColor=none;shape=mxgraph.aws4.${stencil};`
  )
}

/** AWS Architecture Icons category palette. */
const C = {
  network: '#8C4FFF',
  compute: '#ED7100',
  storage: '#7AA116',
  database: '#527FFF',
  security: '#DD344C',
  neutral: '#232F3E',
}

const EDGE =
  'edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;' +
  'endArrow=block;endFill=1;strokeWidth=2;strokeColor=#64748B;fontSize=10;fontColor=#334155;' +
  'labelBackgroundColor=#FFFFFF;align=center;verticalAlign=bottom;spacingBottom=2;'

const EDGE_DASH = `${EDGE}dashed=1;dashPattern=6 4;strokeColor=#94A3B8;`

/** Free-floating annotation (no border, no fill). */
const NOTE = 'text;html=1;align=left;verticalAlign=top;whiteSpace=wrap;fontSize=10;fontColor=#475569;'

/** Nestable boundary (VPC / subnet). */
function container(fill: string, stroke: string, font: string): string {
  return (
    'rounded=1;arcSize=4;whiteSpace=wrap;html=1;container=1;collapsible=0;' +
    'verticalAlign=top;align=left;spacingLeft=14;spacingTop=8;' +
    `fontSize=13;fontStyle=1;fontColor=${font};fillColor=${fill};strokeColor=${stroke};`
  )
}

const LEGEND_HTML = [
  '<b>Request flow</b><br/>',
  '<b>1.</b> Client &rarr; Route 53 (DNS) &rarr; AWS WAF (inspect) &rarr; CloudFront (TLS terminated + cached at the edge)<br/>',
  '<b>2.</b> CloudFront &rarr; Application Load Balancer in the public subnets (origin over HTTPS/443)<br/>',
  '<b>3.</b> ALB &rarr; EC2 Auto Scaling in the private application subnet<br/>',
  '<b>4.</b> EC2 &rarr; RDS Multi-AZ in the private data subnet (SQL/5432)<br/>',
  '<b>5.</b> Outbound traffic from the private subnets egresses via the NAT Gateway<br/>',
  '<b>6.</b> CloudFront serves static assets directly from Amazon S3',
].join('')

/**
 * Starter canvas for a new AWS architecture diagram.
 *
 * A two-tier reference architecture: a global edge tier (Route 53 / WAF /
 * CloudFront / S3) outside the network, and a VPC whose subnets are real
 * draw.io containers - the services inside them are genuine children, so
 * resizing a subnet carries its services with it and the diagram stays
 * coherent while it is being edited.
 *
 * `region` is surfaced in the VPC label because a proposal that names the
 * wrong region is worse than one that names none.
 */
export function buildStarterXml(customerName: string, calculatorUrl: string, region = 'us-east-1'): string {
  const hasCalc = !!calculatorUrl.trim()
  const calcValue = hasCalc
    ? `<a href="${calculatorUrl.trim()}" target="_blank" style="color:#7C2D12;text-decoration:underline;"><b>AWS Pricing Calculator</b> — click to open this estimate</a>`
    : 'No AWS Pricing Calculator estimate linked yet'
  const calcStyle = hasCalc
    ? 'rounded=1;arcSize=40;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;fontSize=11;fontColor=#7C2D12;fillColor=#FFEDD5;strokeColor=#FDBA74;spacing=8;'
    : 'rounded=1;arcSize=40;whiteSpace=wrap;html=1;align=center;verticalAlign=middle;fontSize=11;fontColor=#9CA3AF;fillColor=#F9FAFB;strokeColor=#E5E7EB;dashed=1;spacing=8;'

  // Authored in absolute canvas coordinates; `geometry()` below converts each
  // child to parent-relative geometry, which is what mxGraph expects.
  const cells: Cell[] = [
    {
      id: 'hdr',
      value: escXml(`${customerName} — AWS Reference Architecture`),
      style: 'text;html=1;align=left;verticalAlign=middle;whiteSpace=wrap;fontSize=19;fontStyle=1;fontColor=#064E3B;',
      x: 30,
      y: 20,
      w: 900,
      h: 32,
    },
    {
      id: 'calc',
      value: escXml(calcValue),
      style: calcStyle,
      x: 30,
      y: 62,
      w: 620,
      h: 30,
    },

    // ---- Global / edge tier (deliberately outside the VPC) -------------
    {
      id: 'users',
      value: 'Client / Users',
      style: awsIcon('users', C.neutral),
      x: 40,
      y: 150,
      w: 80,
      h: 80,
    },
    {
      id: 'r53',
      value: 'Amazon Route 53',
      style: awsIcon('route_53', C.network),
      x: 190,
      y: 150,
      w: 80,
      h: 80,
    },
    {
      id: 'waf',
      value: 'AWS WAF',
      style: awsIcon('waf', C.security),
      x: 340,
      y: 150,
      w: 80,
      h: 80,
    },
    {
      id: 'cf',
      value: 'Amazon CloudFront',
      style: awsIcon('cloudfront', C.network),
      x: 490,
      y: 150,
      w: 80,
      h: 80,
    },
    {
      id: 's3',
      value: 'Amazon S3 (static origin)',
      style: awsIcon('s3', C.storage),
      x: 490,
      y: 350,
      w: 80,
      h: 80,
    },

    // ---- VPC -----------------------------------------------------------
    {
      id: 'vpc',
      value: `VPC — ${escXml(region)} · 10.0.0.0/16 · 2 Availability Zones`,
      style: `${container('#F5F9FD', '#B6C8D9', '#1E3A5F')}dashed=1;strokeWidth=2;`,
      x: 700,
      y: 100,
      w: 820,
      h: 620,
    },

    // ---- Public subnets -------------------------------------------------
    {
      id: 'pub',
      value: 'Public Subnets · 10.0.0.0/20 · internet-facing',
      style: container('#ECFDF5', '#6EE7B7', '#065F46'),
      x: 720,
      y: 150,
      w: 780,
      h: 200,
      parent: 'vpc',
    },
    {
      id: 'igw',
      value: 'Internet Gateway',
      style: awsIcon('internet_gateway', C.network),
      x: 745,
      y: 215,
      w: 80,
      h: 80,
      parent: 'pub',
    },
    {
      id: 'alb',
      value: 'Application Load Balancer',
      style: awsIcon('application_load_balancer', C.network),
      x: 900,
      y: 215,
      w: 80,
      h: 80,
      parent: 'pub',
    },
    {
      id: 'nat',
      value: 'NAT Gateway',
      style: awsIcon('nat_gateway', C.network),
      x: 1060,
      y: 215,
      w: 80,
      h: 80,
      parent: 'pub',
    },
    {
      id: 'sgPub',
      value: escXml(
        'SG-public: ALB accepts 443 from CloudFront only.<br/>No other inbound port is open to 0.0.0.0/0.',
      ),
      style: NOTE,
      x: 1180,
      y: 225,
      w: 300,
      h: 110,
      parent: 'pub',
    },

    // ---- Private application subnet -------------------------------------
    {
      id: 'app',
      value: 'Private Subnet — App · AZ 1a · 10.0.1.0/24',
      style: container('#EFF6FF', '#93C5FD', '#1E40AF'),
      x: 720,
      y: 380,
      w: 380,
      h: 320,
      parent: 'vpc',
    },
    {
      id: 'asg',
      value: 'EC2 Auto Scaling',
      style: awsIcon('autoscaling', C.compute),
      x: 870,
      y: 440,
      w: 80,
      h: 80,
      parent: 'app',
    },
    {
      id: 'sgApp',
      value: escXml(
        'SG-app: inbound 8080 from the ALB security group only.<br/>Outbound to the data subnet and to the internet via NAT.',
      ),
      style: NOTE,
      x: 745,
      y: 590,
      w: 330,
      h: 90,
      parent: 'app',
    },

    // ---- Private data subnet --------------------------------------------
    {
      id: 'data',
      value: 'Private Subnet — Data · AZ 1b · 10.0.20.0/24',
      style: container('#FFF7ED', '#FDBA74', '#9A3412'),
      x: 1130,
      y: 380,
      w: 370,
      h: 320,
      parent: 'vpc',
    },
    {
      id: 'rds',
      value: 'Amazon RDS Multi-AZ',
      // the "rds multi az" stencil is natively 44x32.7, so this box is wider
      // than it is tall to avoid the aspect=fixed letterboxing shrinking it
      style: awsIcon('rds_multi_az', C.database),
      x: 1263,
      y: 441,
      w: 104,
      h: 78,
      parent: 'data',
    },
    {
      id: 'sgData',
      value: escXml(
        'SG-data: inbound 5432 from the app security group only.<br/>Encrypted at rest, automated backups, no public route.',
      ),
      style: NOTE,
      x: 1155,
      y: 590,
      w: 320,
      h: 90,
      parent: 'data',
    },

    // ---- Legend ----------------------------------------------------------
    {
      id: 'legend',
      value: escXml(LEGEND_HTML),
      style:
        'rounded=1;arcSize=4;whiteSpace=wrap;html=1;container=1;collapsible=0;align=left;' +
        'verticalAlign=top;spacingLeft=14;spacingTop=10;fontSize=11;fontColor=#334155;' +
        'lineHeight=1.5;fillColor=#FFFFFF;strokeColor=#CBD5E1;dashed=1;',
      x: 30,
      y: 790,
      w: 960,
      h: 130,
    },
  ]

  const edges: Array<[string, string, string, string, boolean?]> = [
    ['e1', 'users', 'r53', 'DNS lookup'],
    ['e2', 'r53', 'waf', 'HTTPS'],
    ['e3', 'waf', 'cf', 'inspect + cache'],
    ['e4', 'cf', 's3', 'static assets', true],
    ['e5', 'cf', 'igw', 'origin HTTPS 443'],
    ['e6', 'igw', 'alb', 'forward to ALB'],
    ['e7', 'alb', 'asg', 'app traffic 8080'],
    ['e8', 'asg', 'rds', 'SQL 5432'],
    ['e9', 'asg', 'nat', 'outbound via NAT', true],
  ]

  const origin = new Map(cells.map((c) => [c.id, c]))
  const geometry = (c: Cell): string => {
    const parent = c.parent ? origin.get(c.parent) : undefined
    const x = parent ? c.x - parent.x : c.x
    const y = parent ? c.y - parent.y : c.y
    return `<mxGeometry x="${x}" y="${y}" width="${c.w}" height="${c.h}" as="geometry"/>`
  }

  const vertexXml = cells
    .map(
      (c) =>
        `<mxCell id="${c.id}" value="${c.value}" style="${c.style}" vertex="1" ` +
        `parent="${c.parent ?? '1'}">${geometry(c)}</mxCell>`,
    )
    .join('')

  const edgeXml = edges
    .map(
      ([id, source, target, label, dashed]) =>
        `<mxCell id="${id}" value="${escXml(label)}" style="${dashed ? EDGE_DASH : EDGE}" ` +
        `edge="1" parent="1" source="${source}" target="${target}">` +
        '<mxGeometry relative="1" as="geometry"/></mxCell>',
    )
    .join('')

  return (
    '<mxfile host="app.diagrams.net"><diagram id="aws-reference" name="AWS Reference Architecture">' +
    '<mxGraphModel dx="1500" dy="950" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" ' +
    'arrows="1" fold="1" page="1" pageScale="1" pageWidth="1620" pageHeight="960" math="0" shadow="0">' +
    `<root><mxCell id="0"/><mxCell id="1" parent="0"/>${vertexXml}${edgeXml}</root>` +
    '</mxGraphModel></diagram></mxfile>'
  )
}
