export function escXml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

export function buildStarterXml(customerName: string, calculatorUrl: string): string {
  const title = `${customerName} — AWS Architecture`
  const linkValue = calculatorUrl
    ? `<a href="${escXml(calculatorUrl)}" target="_blank" style="color:#FFFFFF;text-decoration:none;"><b>AWS Pricing Calculator</b> — click to open this estimate</a>`
    : `AWS Pricing Calculator`
  const calcStyle = calculatorUrl
    ? 'text;html=1;align=center;verticalAlign=middle;fontSize=13;fontColor=#FFFFFF;fontStyle=1;fillColor=#FF9900;strokeColor=none;rounded=1;spacing=10;'
    : 'rounded=1;whiteSpace=wrap;html=1;fillColor=#FF9900;strokeColor=none;fontColor=#FFFFFF;fontSize=12;'

  const nodes: Array<[string, string, string, number, number, number, number]> = [
    ['hdr', escXml(title), 'text;html=1;align=left;verticalAlign=top;fontSize=16;fontStyle=1;fontColor=#064e3b;', 20, 20, 800, 30],
    ['client', 'Client / Users', 'shape=mxgraph.aws4.client;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;whiteSpace=wrap;', 40, 320, 80, 80],
    ['r53', 'Amazon Route 53', 'shape=mxgraph.aws4.route53;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;whiteSpace=wrap;', 220, 330, 90, 90],
    ['cf', 'Amazon CloudFront', 'shape=mxgraph.aws4.cloudFront;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;whiteSpace=wrap;', 400, 330, 110, 110],
    ['s3', 'Amazon S3', 'shape=mxgraph.aws4.S3;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;whiteSpace=wrap;', 400, 150, 110, 110],
    ['vpc', 'VPC — us-east-1', 'rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;fontStyle=1;fontSize=12;fillColor=#f0f6fb;strokeColor=#b6c8d9;dashed=1;', 570, 180, 520, 380],
    ['alb', 'Application Load Balancer', 'shape=mxgraph.aws4.elb_application;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;whiteSpace=wrap;', 600, 240, 160, 130],
    ['asg', 'Auto Scaling (EC2)', 'shape=mxgraph.aws4.autoScaling;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;whiteSpace=wrap;', 600, 400, 160, 130],
    ['rds', 'Amazon RDS', 'shape=mxgraph.aws4.rds_multi_a_z;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;whiteSpace=wrap;', 800, 400, 160, 130],
    ['calc', escXml(linkValue), calcStyle, 40, 560, 520, 44],
  ]

  const edges: Array<[string, string, string]> = [
    ['e1', 'client', 'r53'],
    ['e2', 'r53', 'cf'],
    ['e3', 'cf', 's3'],
    ['e4', 'cf', 'alb'],
    ['e5', 'alb', 'asg'],
    ['e6', 'asg', 'rds'],
  ]

  const edgeStyle = 'edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=block;'

  const cells = [
    '<mxCell id="0"/>',
    '<mxCell id="1" parent="0"/>',
    ...nodes.map(
      ([id, value, style, x, y, w, h]) =>
        `<mxCell id="${id}" value="${value}" style="${style}" vertex="1" parent="1"><mxGeometry x="${x}" y="${y}" width="${w}" height="${h}" as="geometry"/></mxCell>`,
    ),
    ...edges.map(
      ([id, source, target]) =>
        `<mxCell id="${id}" style="${edgeStyle}" edge="1" parent="1" source="${source}" target="${target}"><mxGeometry relative="1" as="geometry"/></mxCell>`,
    ),
  ]

  return `<mxfile host="app.diagrams.net"><diagram id="aws-starter" name="AWS Architecture"><mxGraphModel dx="900" dy="650" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1169" pageHeight="826" math="0" shadow="0"><root>${cells.join('')}</root></mxGraphModel></diagram></mxfile>`
}