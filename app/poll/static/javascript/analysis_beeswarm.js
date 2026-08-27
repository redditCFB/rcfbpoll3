(function () {
    'use strict';
    const container = document.getElementById('analysis-beeswarm');
    if (!container || typeof d3 === 'undefined') return;
    const results = JSON.parse(document.getElementById('analysis-beeswarm-data').textContent);
    const logoTemplate = container.dataset.logoUrlTemplate;
    const markerSize = 36;
    const markerGap = 4;
    const axisHeight = 42;
    results.forEach(result => {
        result.logo_url = logoTemplate.replace('{handle}', result.team_handle);
    });
    function render() {
        const width = Math.max(container.clientWidth, 1);
        const narrow = width < 480;
        const columns = Math.max(1, Math.floor((width - 24) / (markerSize + markerGap)));
        const rows = Math.max(1, Math.ceil(results.length / columns));
        const height = Math.max(150, (narrow ? 46 : 40) + rows * (markerSize + markerGap) + axisHeight);
        const margin = { top: 8, right: 12, bottom: axisHeight, left: 12 };
        const x = d3.scaleLinear().domain([0, 25]).range([
            margin.left + markerSize / 2,
            width - margin.right - markerSize / 2,
        ]);
        const plotHeight = height - margin.top - margin.bottom;
        const y = margin.top + plotHeight / 2;
        d3.select(container).selectAll('.analysis-beeswarm-chart').remove();
        const chart = d3.select(container).append('div').attr('class', 'analysis-beeswarm-chart');
        const svg = chart.append('svg').attr('viewBox', '0 0 ' + width + ' ' + height)
            .attr('role', 'img').attr('aria-labelledby', 'beeswarm-heading');
        const axis = d3.axisBottom(x).tickValues([0, 5, 10, 15, 20, 25]);
        svg.append('g').attr('transform', 'translate(0,' + (height - margin.bottom) + ')').call(axis);
        svg.append('text').attr('x', width / 2).attr('y', height - 4)
            .attr('text-anchor', 'middle').text('Points per voter (PPV)');
        const nodes = results.map(result => ({
            ...result,
            x: x(Math.max(0, Math.min(25, result.points_per_voter))),
            y: y,
            targetX: x(Math.max(0, Math.min(25, result.points_per_voter))),
        }));
        const simulation = d3.forceSimulation(nodes)
            .force('x', d3.forceX(node => node.targetX).strength(1))
            .force('y', d3.forceY(y).strength(0.12))
            .force('collide', d3.forceCollide((markerSize + markerGap) / 2))
            .stop();
        for (let i = 0; i < 180; i += 1) simulation.tick();
        const tooltip = chart.append('div').attr('class', 'analysis-beeswarm-tooltip')
            .attr('role', 'tooltip').style('display', 'none');
        function showTooltip(event, node) {
            tooltip.text('Rank: #' + node.rank + '\nTeam: ' + node.team_name +
                '\nPPV: ' + Number(node.points_per_voter).toFixed(2)).style('display', 'block');
            const bounds = container.getBoundingClientRect();
            tooltip.style('left', (event.clientX - bounds.left + 8) + 'px')
                .style('top', (event.clientY - bounds.top - 8) + 'px');
        }
        function hideTooltip() { tooltip.style('display', 'none'); }
        svg.selectAll('image').data(nodes).join('image')
            .attr('class', 'team-marker')
            .attr('x', node => node.x - markerSize / 2).attr('y', node => node.y - markerSize / 2)
            .attr('width', markerSize).attr('height', markerSize)
            .attr('preserveAspectRatio', 'xMidYMid meet').attr('href', node => node.logo_url)
            .attr('opacity', node => node.rank > 25 ? 0.5 : 1)
            .attr('tabindex', 0).attr('role', 'button')
            .attr('aria-label', node => 'Rank #' + node.rank + ', ' + node.team_name +
                ', PPV ' + Number(node.points_per_voter).toFixed(2))
            .on('mouseenter focus', showTooltip).on('mousemove', showTooltip)
            .on('mouseleave blur', hideTooltip).on('click', showTooltip);
    }
    let resizeFrame;
    new ResizeObserver(() => {
        cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(render);
    }).observe(container);
    render();
}());
