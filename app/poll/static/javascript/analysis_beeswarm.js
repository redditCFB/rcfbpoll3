(function () {
    'use strict';

    const container = document.getElementById('analysis-beeswarm');
    if (!container || typeof d3 === 'undefined') return;

    const results = JSON.parse(document.getElementById('analysis-beeswarm-data').textContent);
    const logoTemplate = container.dataset.logoUrlTemplate;
    const markerSize = 36;
    const markerGap = 4;
    const markerDiameter = markerSize + markerGap;
    const axisHeight = 42;
    const horizontalPadding = 12;
    const mobileBreakpoint = 768;
    const mobilePlotHeight = 560;
    const epsilon = 1e-7;

    results.forEach(result => {
        result.logo_url = logoTemplate.replace('{handle}', result.team_handle);
    });

    function fixedSemanticBeeswarm(nodes) {
        nodes.sort((a, b) => a.semantic - b.semantic || a.rank - b.rank);
        nodes.forEach((node, index) => {
            const candidates = [0];

            for (let previousIndex = 0; previousIndex < index; previousIndex += 1) {
                const previous = nodes[previousIndex];
                const dSemantic = node.semantic - previous.semantic;
                const absoluteSemantic = Math.abs(dSemantic);
                if (absoluteSemantic < markerDiameter) {
                    const dPacked = Math.sqrt(markerDiameter ** 2 - absoluteSemantic ** 2);
                    candidates.push(previous.packed + dPacked, previous.packed - dPacked);
                    candidates.push(previous.packed + markerDiameter, previous.packed - markerDiameter);
                }
            }

            candidates.sort((a, b) => Math.abs(a) - Math.abs(b) || a - b);
            node.packed = candidates.find(candidate => nodes
                .slice(0, index)
                .every(previous => {
                    const dSemantic = node.semantic - previous.semantic;
                    const dPacked = candidate - previous.packed;
                    return Math.hypot(dSemantic, dPacked) >= markerDiameter - epsilon;
                }));
        });
        return nodes;
    }

    function showTooltip(chart, element, pointerEvent, node) {
        const tooltip = chart.select('.analysis-beeswarm-tooltip');
        const chartBounds = chart.node().getBoundingClientRect();
        const elementBounds = element.getBoundingClientRect();
        const hasPointer = pointerEvent && pointerEvent.type !== 'focus' &&
            Number.isFinite(pointerEvent.clientX) && Number.isFinite(pointerEvent.clientY);
        const left = hasPointer
            ? pointerEvent.clientX - chartBounds.left + 8
            : elementBounds.left - chartBounds.left + markerSize / 2;
        const top = hasPointer
            ? pointerEvent.clientY - chartBounds.top - 8
            : elementBounds.top - chartBounds.top - 8;

        tooltip.text('Rank: #' + node.rank + '\nTeam: ' + node.team_name +
            '\nPPV: ' + Number(node.points_per_voter).toFixed(2))
            .style('display', 'block')
            .style('left', left + 'px')
            .style('top', top + 'px');

        const tooltipBounds = tooltip.node().getBoundingClientRect();
        const clampedLeft = Math.max(0, Math.min(
            left, chartBounds.width - tooltipBounds.width));
        const clampedTop = Math.max(0, Math.min(
            top, chartBounds.height - tooltipBounds.height));
        tooltip.style('left', clampedLeft + 'px').style('top', clampedTop + 'px');
    }

    function render() {
        const width = Math.max(container.clientWidth, 1);
        const mobile = width < mobileBreakpoint;
        const margin = mobile
            ? { top: 8, right: horizontalPadding, bottom: 8, left: 52 }
            : { top: 8, right: horizontalPadding, bottom: axisHeight, left: horizontalPadding };

        let nodes;
        let height;
        let semanticScale;
        let axis;
        let axisTransform;
        let axisLabel;
        if (mobile) {
            semanticScale = d3.scaleLinear().domain([0, 25]).range([
                margin.top + markerSize / 2 + mobilePlotHeight,
                margin.top + markerSize / 2,
            ]).clamp(true);
            const plotLeft = margin.left + markerSize / 2;
            const plotRight = width - margin.right - markerSize / 2;
            const packedCenter = (plotLeft + plotRight) / 2;
            nodes = fixedSemanticBeeswarm(results.map(result => ({
                ...result,
                semantic: semanticScale(result.points_per_voter),
            })));
            const minPacked = d3.min(nodes, node => node.packed) || 0;
            const maxPacked = d3.max(nodes, node => node.packed) || 0;
            const packedOffset = packedCenter - (minPacked + maxPacked) / 2;
            nodes.forEach(node => {
                node.x = node.packed + packedOffset;
                node.y = node.semantic;
            });
            height = margin.top + markerSize / 2 + mobilePlotHeight +
                markerSize / 2 + margin.bottom;
            axis = d3.axisLeft(semanticScale).tickValues([0, 5, 10, 15, 20, 25]);
            axisTransform = 'translate(' + margin.left + ',0)';
            axisLabel = svg => svg.append('text')
                .attr('transform', 'rotate(-90)')
                .attr('x', -(height / 2))
                .attr('y', 14)
                .attr('text-anchor', 'middle')
                .text('Points per voter (PPV)');
        } else {
            semanticScale = d3.scaleLinear().domain([0, 25]).range([
                margin.left + markerSize / 2,
                width - margin.right - markerSize / 2,
            ]).clamp(true);
            nodes = fixedSemanticBeeswarm(results.map(result => ({
                ...result,
                semantic: semanticScale(result.points_per_voter),
            })));
            const minPacked = d3.min(nodes, node => node.packed) || 0;
            const maxPacked = d3.max(nodes, node => node.packed) || 0;
            const plotTop = margin.top + markerSize / 2;
            nodes.forEach(node => {
                node.x = node.semantic;
                node.y = plotTop + node.packed - minPacked;
            });
            const swarmHeight = maxPacked - minPacked;
            height = plotTop + swarmHeight + markerSize / 2 + axisHeight;
            axis = d3.axisBottom(semanticScale).tickValues([0, 5, 10, 15, 20, 25]);
            axisTransform = 'translate(0,' + (height - margin.bottom) + ')';
            axisLabel = svg => svg.append('text')
                .attr('x', width / 2)
                .attr('y', height - 4)
                .attr('text-anchor', 'middle')
                .text('Points per voter (PPV)');
        }

        d3.select(container).selectAll('.analysis-beeswarm-chart').remove();
        const chart = d3.select(container).append('div')
            .attr('class', 'analysis-beeswarm-chart');
        const svg = chart.append('svg')
            .attr('viewBox', '0 0 ' + width + ' ' + height)
            .attr('role', 'img')
            .attr('aria-labelledby', 'beeswarm-heading');
        svg.append('g').attr('transform', axisTransform).call(axis);
        axisLabel(svg);

        const tooltip = chart.append('div')
            .attr('class', 'analysis-beeswarm-tooltip')
            .attr('role', 'tooltip')
            .style('display', 'none');

        svg.selectAll('image').data(nodes).join('image')
            .attr('class', 'team-marker')
            .attr('x', node => node.x - markerSize / 2)
            .attr('y', node => node.y - markerSize / 2)
            .attr('width', markerSize)
            .attr('height', markerSize)
            .attr('preserveAspectRatio', 'xMidYMid meet')
            .attr('href', node => node.logo_url)
            .attr('opacity', node => node.rank > 25 ? 0.5 : 1)
            .attr('tabindex', 0)
            .attr('role', 'button')
            .attr('aria-label', node => 'Rank #' + node.rank + ', ' + node.team_name +
                ', PPV ' + Number(node.points_per_voter).toFixed(2))
            .on('mouseenter focus', function (event, node) {
                showTooltip(chart, this, event, node);
            })
            .on('mousemove', function (event, node) {
                showTooltip(chart, this, event, node);
            })
            .on('mouseleave blur', function () {
                tooltip.style('display', 'none');
            })
            .on('click', function (event, node) {
                showTooltip(chart, this, event, node);
            });
    }

    let resizeFrame;
    new ResizeObserver(() => {
        cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(render);
    }).observe(container);
    render();
}());
